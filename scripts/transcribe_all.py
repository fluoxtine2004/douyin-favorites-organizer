# -*- coding: utf-8 -*-
"""
全量逐字稿转写（2026-09-26 干净重抓后版本）
策略：优先复用 media/<id>/video.mp4（本地已有 407 条，直链已过期 403）
      → 抽 16k wav → faster-whisper(small, local) 转写 → 抽关键帧
      → 写回 favorites.json（transcript/points/frames/processed_at）
断点续传：已有 transcript 的跳过。缺失本地视频的尝试直链下载。
用法：
  python transcribe_all.py            # 全量
  python transcribe_all.py --limit 20 # 只跑前 20 条（冒烟）
"""
import json
import re
import sys
import time
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "favorites.json"
MEDIA_DIR = ROOT / "media"
COOKIES_FILE = ROOT / "data" / "cookies.txt"

sys.path.insert(0, str(Path(__file__).parent))
from ffmpegutil import get_ffmpeg  # noqa: E402

FFMPEG = get_ffmpeg()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def log(msg):
    print(msg, flush=True)


def ts(sec):
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def cookie_header():
    pairs = []
    for line in COOKIES_FILE.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) == 7:
            pairs.append(p[5] + "=" + p[6])
    return "; ".join(pairs)


def download_video(v, wd):
    existing = wd / "video.mp4"
    if existing.exists() and existing.stat().st_size > 50_000:
        return existing
    urls = v.get("play_urls") or []
    out = wd / "video.mp4"
    for u in urls:
        try:
            req = urllib.request.Request(u, headers={
                "User-Agent": UA, "Referer": "https://www.douyin.com/",
                "Cookie": cookie_header()})
            with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as f:
                while True:
                    c = r.read(1 << 18)
                    if not c:
                        break
                    f.write(c)
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


def extract_audio(video_file, wd):
    out = wd / "audio.wav"
    if out.exists() and out.stat().st_size > 10_000:
        return out
    cmd = [str(FFMPEG), "-y", "-i", str(video_file), "-vn", "-ac", "1", "-ar", "16000", str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 10_000:
            return out
    except Exception:
        pass
    return None


def extract_frames(video_file, wd, duration):
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
        from faster_whisper import WhisperModel
        local = ROOT / "models" / "faster-whisper-small"
        model_id = str(local) if (local / "model.bin").exists() else "small"
        log(f"  加载 whisper（{model_id}）…")
        _whisper = WhisperModel(model_id, device="cpu", compute_type="int8")
    return _whisper


def transcribe(audio):
    model = get_whisper()
    segments, info = model.transcribe(str(audio), language="zh", vad_filter=True)
    lines, plain = [], []
    for seg in segments:
        lines.append(f"[{ts(seg.start)}] {seg.text.strip()}")
        plain.append(seg.text.strip())
    return "\n".join(lines), "".join(plain), info.duration or 0


def summarize_points(plain_text, max_points=4):
    text = re.sub(r"\s+", "", plain_text)
    if not text:
        return []
    sents = [s for s in re.split(r"[。！？!?；;]", text) if len(s) >= 8]
    key = ["首先", "然后", "其次", "最后", "注意", "关键", "重点", "第一", "第二", "第三",
           "建议", "一定", "不要", "切记", "核心", "原理", "方法", "步骤"]
    scored = []
    for s in sents:
        sc = sum(2 for k in key if k in s) + (1 if re.search(r"\d", s) else 0)
        scored.append((sc, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:max_points]]


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    todo = []
    for f in data.get("folders", []):
        for v in f.get("videos", []):
            if v.get("transcript"):
                continue
            todo.append(v)
    total_pending = len(todo)
    if limit:
        todo = todo[:limit]
    if not todo:
        log("没有待转写视频。")
        return

    log(f"待转写 {total_pending} 条，本批处理 {len(todo)} 条…")
    done = failed = 0
    t0 = time.time()
    for i, v in enumerate(todo, 1):
        vid = str(v["id"])
        wd = MEDIA_DIR / vid
        wd.mkdir(parents=True, exist_ok=True)
        log(f"[{i}/{len(todo)}] {v.get('title', '')[:36]} ({vid})")
        try:
            vf = wd / "video.mp4"
            if not (vf.exists() and vf.stat().st_size > 50_000):
                vf = download_video(v, wd)
                if not vf:
                    v["dl_failed_recently"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    failed += 1
                    log("  !! 无本地视频且直链失败")
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
                log("  !! 转写为空")
                continue
            v["transcript"] = stamp_text
            v["points"] = summarize_points(plain)
            fr_list = extract_frames(vf, wd, dur)
            v["frames"] = [{"url": f["path"], "t": f["t"],
                            "cap": f"{f['t'] // 60}:{f['t'] % 60:02d}"} for f in fr_list]
            v["processed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            v.pop("dl_failed_recently", None)
            done += 1
            DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            log(f"  ✅ {len(plain)}字, 要点{len(v['points'])}, 截图{len(fr_list)}, 累计{time.time()-t0:.0f}s")
        except Exception as e:
            failed += 1
            log(f"  !! 异常：{e}")

    log(f"批次完成：成功 {done} / 失败 {failed} / 共 {len(todo)}，总耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
