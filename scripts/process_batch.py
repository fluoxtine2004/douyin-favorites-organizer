# -*- coding: utf-8 -*-
"""
批次处理：对 favorites.json 中尚未处理的视频执行
  直接下载视频（抓取时捕获的 play_addr 直链 + 浏览器 Cookie）
  → 提取音频（ffmpeg 16k 单声道 wav）
  → 语音转写（faster-whisper, small 模型）
  → 关键帧截图（ffmpeg）
并把 transcript / points / frames 写回 favorites.json（增量，不重复处理）。
用法：
  python process_batch.py [--limit 15] [--only-ids id1,id2]
说明：
  - 依赖 fetch_favorites.py 抓取时写入的 play_urls（直链有时效，过期则需先重新抓取）
  - 依赖 export_cookies.py 生成的 data/cookies.txt
"""
import json
import re
import sys as _sys
_sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from lockutil import acquire, release  # noqa
from enrich import clean_points  # noqa  ★ 要点护栏单一来源（坑位 H / O）
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "favorites.json"
MEDIA_DIR = ROOT / "media"
COOKIES_FILE = ROOT / "data" / "cookies.txt"
from ffmpegutil import get_ffmpeg  # noqa: E402
# imageio-ffmpeg 自带 gyan.dev essentials 构建，支持 mp4/h264；
# 兜底会扫 Playwright 自带的精简版（仅 webm/vp8），必要时请自行指定 FFMPEG_BINARY。
FFMPEG = get_ffmpeg()
PY = Path(sys.executable)
WHISPER_MODEL = "small"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def log(msg):
    print(msg, flush=True)


def ts(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def cookie_header() -> str:
    pairs = []
    for line in COOKIES_FILE.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) == 7:
            pairs.append(parts[5] + "=" + parts[6])
    return "; ".join(pairs)


def download_video(v, wd: Path):
    """用直链 + Cookie 下载视频，返回文件路径或 None（已有文件则直接复用）"""
    existing = wd / "video.mp4"
    if existing.exists() and existing.stat().st_size > 50_000:
        return existing
    urls = v.get("play_urls") or []
    out = wd / "video.mp4"
    for u in urls:
        try:
            req = urllib.request.Request(u, headers={
                "User-Agent": UA,
                "Referer": "https://www.douyin.com/",
                "Cookie": cookie_header(),
            })
            with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as f:
                while True:
                    chunk = r.read(1 << 18)
                    if not chunk:
                        break
                    f.write(chunk)
            if out.exists() and out.stat().st_size > 50_000:
                return out
        except Exception:
            continue
    if out.exists():
        try:
            out.unlink()
        except Exception:
            pass
    return None


def extract_audio(video_file: Path, wd: Path):
    """ffmpeg 提取 16k 单声道 wav（whisper 友好）"""
    out = wd / "audio.wav"
    cmd = [str(FFMPEG), "-y", "-i", str(video_file), "-vn", "-ac", "1", "-ar", "16000", str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 10_000:
            return out
    except Exception:
        pass
    return None


def extract_frames(video_file: Path, wd: Path, duration: float):
    """抽关键帧：短视频 3 帧（25%/55%/85%）；长视频（>10min）每 2 分钟 1 帧（最多 12 帧）
    返回 [{'path':..., 't':秒}]"""
    if duration and duration > 600:
        step = 120
        times = list(range(step // 2, int(duration), step))[:12]
    else:
        fracs = [0.25, 0.55, 0.85]
        times = [max(1.0, duration * f) if duration else (i + 1) * 30 for i, f in enumerate(fracs)]
    frames = []
    for i, t in enumerate(times):
        out = wd / f"kf_{int(t):05d}.jpg"
        cmd = [str(FFMPEG), "-y", "-ss", f"{float(t):.1f}", "-i", str(video_file),
               "-frames:v", "1", "-q:v", "3", str(out)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode == 0 and out.exists():
                frames.append({"path": str(out), "t": int(t)})
        except Exception:
            pass
    return frames


_whisper = None


def get_whisper():
    global _whisper
    if _whisper is None:
        import os
        from faster_whisper import WhisperModel
        # 优先用本地模型（ModelScope 下载，规避 HF 网络问题）
        local = ROOT / "models" / "faster-whisper-small"
        model_id = str(local) if (local / "model.bin").exists() else WHISPER_MODEL
        if not model_id.startswith(str(ROOT)):
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        log(f"  加载 whisper 模型（{model_id}）…")
        _whisper = WhisperModel(model_id, device="cpu", compute_type="int8")
    return _whisper


def transcribe(audio: Path):
    """转写，返回 (带时间戳文本, 纯文本, 时长秒)"""
    model = get_whisper()
    segments, info = model.transcribe(str(audio), language="zh", vad_filter=True)
    lines, plain = [], []
    for seg in segments:
        line = f"[{ts(seg.start)}] {seg.text.strip()}"
        lines.append(line)
        plain.append(seg.text.strip())
    return "\n".join(lines), "".join(plain), info.duration or 0


def summarize_points(transcript_text: str, title: str, max_points: int = 3):
    """从逐字稿提炼要点（规则式兜底）。
    后续由 agent 在周报阶段写 data/llm_notes.json 覆盖（LLM 要点优先）。

    ⚠ 坑位 H：抖音逐字稿几乎没有句号，只按 [。！？；] 切会切出「一整篇」当要点
      （2026-10-08 实测：3 条新视频的 points 分别是 1129/493/177 字）。
      所以这里 ① 逗号级联切分 ② 结果一律过 clean_points 同一道闸门
      （≤3 条、单条 ≤90 字、>200 字整条丢弃），与 enrich / generate_outputs /
      build_dashboard 三处同源，不再各写各的。

    ⚠ 坑位 U（2026-10-10）：whisper 输出的中文逐字稿**经常整篇零标点**
      （每行 [mm:ss] 短语，行尾无句读），逗号级联也切不动 → 要点恒为空。
    ⚠ 坑位 AC（2026-10-10）：若传入的是 `plain`（各段 text 直接拼接、无时间戳无换行），
      「按行切」同样失效 → 必须再加一级**固定长度滑窗**兜底；
      且当所有候选都 >120 字（长稿只有 2~3 个句号）时也要滑窗，否则 clean_points 会整条丢弃。
    """
    text = re.sub(r"\s+", "", transcript_text)
    if not text:
        return []
    sents = [s for s in re.split(r"[。！？!?；;]", text) if len(s) >= 8]
    if len(sents) < 2:
        sents = [s for s in re.split(r"[。！？!?；;，,、]", text) if len(s) >= 8] or sents
    if len(sents) < 2 or all(len(s) > 120 for s in sents):
        buf, lines = "", []
        for line in transcript_text.splitlines():
            body = re.sub(r"^\s*\[\d+:\d+\]\s*", "", line).strip()
            if not body:
                continue
            buf += body
            if len(buf) >= 12:
                lines.append(buf)
                buf = ""
        if buf:
            lines.append(buf)
        if len(lines) >= 2:
            sents = [s for s in lines if len(s) >= 8] or lines
    if len(sents) < 2 or all(len(s) > 120 for s in sents):
        win, step = 22, 11
        if len(text) >= win:
            sents = [text[i:i + win] for i in range(0, len(text) - win + 1, step)]
        else:
            sents = [text]
    key = ["首先", "然后", "其次", "最后", "注意", "关键", "重点", "第一", "第二", "第三",
           "建议", "一定", "不要", "切记", "核心", "原理", "方法", "步骤",
           "可以", "怎么", "为什么", "因为", "所以", "结果", "案例", "数据"]
    scored = []
    for idx, s in enumerate(sents):
        sc = sum(2 for k in key if k in s)
        sc += 1 if re.search(r"\d", s) else 0
        sc += 1 if 14 <= len(s) <= 60 else 0
        sc -= idx * 0.01
        scored.append((sc, s))
    scored.sort(key=lambda x: -x[0])
    return clean_points([s for _, s in scored[: max_points * 4]], max_n=max_points)


def main():
    if not acquire("process_batch"):
        return
    limit = 15
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    only_ids = None
    if "--only-ids" in sys.argv:
        only_ids = set(sys.argv[sys.argv.index("--only-ids") + 1].split(","))

    if not COOKIES_FILE.exists():
        log("缺少 data/cookies.txt，请先运行 export_cookies.py")
        return

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    todo = []
    for f in data.get("folders", []):
        for v in f.get("videos", []):
            if v.get("transcript") or v.get("dl_failed_recently") or v.get("no_transcript"):
                continue
            if only_ids and v["id"] not in only_ids:
                continue
            if not v.get("play_urls"):
                v["no_play_urls"] = True
                continue
            todo.append(v)
    todo = todo[:limit]
    if not todo:
        log("没有待处理视频（全部已有逐字稿或无直链）。")
        if not only_ids:
            DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return

    log(f"本批处理 {len(todo)} 条…")
    done = failed = 0
    t0 = time.time()
    for i, v in enumerate(todo, 1):
        log(f"[{i}/{len(todo)}] {v['title'][:40]}")
        wd = MEDIA_DIR / v["id"]
        wd.mkdir(parents=True, exist_ok=True)
        try:
            vf = download_video(v, wd)
            if not vf:
                v["dl_failed_recently"] = time.strftime("%Y-%m-%d %H:%M:%S")
                failed += 1
                log("  !! 直链下载失败（可能已过期，重新抓取可刷新）")
                continue
            audio = extract_audio(vf, wd)
            if not audio:
                v["dl_failed_recently"] = time.strftime("%Y-%m-%d %H:%M:%S")
                failed += 1
                log("  !! 音频提取失败")
                continue
            stamp_text, plain, dur = transcribe(audio)
            if not plain:
                v["dl_failed_recently"] = time.strftime("%Y-%m-%d %H:%M:%S")
                failed += 1
                continue
            v["transcript"] = stamp_text
            v["points"] = summarize_points(plain, v["title"])
            fr_list = extract_frames(vf, wd, dur)
            v["frames"] = [{"url": f["path"], "t": f["t"],
                            "cap": f"{f['t'] // 60}:{f['t'] % 60:02d}"} for f in fr_list]
            v["processed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            # 媒体文件保留在 media/ 下（video.mp4 可复看，下次运行会复用不再下载）
            done += 1
            DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            log(f"  ✅ 转写完成（{len(plain)} 字），要点 {len(v['points'])} 条，截图 {len(fr_list)} 张，"
                f"累计耗时 {time.time() - t0:.0f}s")
        except Exception as e:
            failed += 1
            log(f"  !! 处理失败：{e}")

    log(f"批次完成：成功 {done} / 失败 {failed} / 共 {len(todo)}")
    # 重新生成产出
    subprocess.run([str(PY), str(ROOT / "scripts" / "generate_outputs.py")], check=False)


    release()


if __name__ == "__main__":
    main()
