# -*- coding: utf-8 -*-
"""
批量补齐：转写 + 关键帧（2026-10-10 建立）

场景：库里 986 条「默认收藏」条目只有过期 play_urls、media/ 下无视频，
     直链已 403。本脚本一条龙：
       ① 用 Playwright 打开视频详情页，拦截 /aweme/v1/web/aweme/detail/ 拿【新鲜直链】
       ② 下载 video.mp4（失败则换下一条 url / 下一条视频）
       ③ ffmpeg 抽 16k 单声道 wav
       ④ faster-whisper(small) 转写
       ⑤ ffmpeg 抽关键帧
       ⑥ 写回 favorites.json（transcript / points / frames / processed_at）
     全程增量落盘，可中断续跑；已有 transcript 的自动跳过。

要点护栏：复用 enrich.clean_points（坑位 H / O），不自己造轮子。

用法：
  python scripts/batch_transcribe.py --limit 50
  python scripts/batch_transcribe.py --only-ids id1,id2
  python scripts/batch_transcribe.py --limit 200 --frames-only   # 只补关键帧（豁免条目）
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lockutil import acquire, release  # noqa
from enrich import clean_points  # noqa  ★ 要点护栏单一来源（坑位 H / O）

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "favorites.json"
MEDIA_DIR = ROOT / "media"
COOKIES_FILE = ROOT / "data" / "cookies.txt"
PROFILE = ROOT / "browser_profile"
PY = Path(sys.executable)

from ffmpegutil import get_ffmpeg  # noqa: E402

FFMPEG = get_ffmpeg()

WHISPER_MODEL = "small"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

# ⚠ 坑位 AA（2026-10-10）：whisper 会把屏幕上的**字幕署名水印**（如「字幕by索兰娅」）
#   当成语音转出来 → 网页出现只有 7 个字的空卡片。与 clean_fake_transcripts.py 同一套判据，
#   在**写盘前**就拦掉，避免脏数据落地（否则要靠清洗链事后补救）。
WM = re.compile(r"字幕\s*by|@[\u4e00-\u9fff]+字幕|听译|机翻|翻译by|subtitle\s*by", re.I)
TS_RE = re.compile(r"\[(\d+):(\d+)\]")
PUNCT = re.compile(r"[\s，。、！？…—,.\!\?~\"'：:；;（）()\[\]【】\-\u3000]")


def real_len(t: str) -> int:
    s = TS_RE.sub("", t or "")
    return len(s) - len(PUNCT.findall(s))


def is_fake_transcript(t: str) -> bool:
    """伪转写：水印署名，或去掉时间戳/标点后不足 8 个实字。"""
    if not t or not t.strip():
        return False
    if WM.search(t):
        return True
    return real_len(t) <= 8


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
        p = line.split("\t")
        if len(p) == 7:
            pairs.append(p[5] + "=" + p[6])
    return "; ".join(pairs)


CK = None


def ck():
    global CK
    if CK is None:
        CK = cookie_header()
    return CK


def download_video(urls, wd: Path, timeout=180):
    """按 url 顺序尝试下载到 wd/video.mp4"""
    existing = wd / "video.mp4"
    if existing.exists() and existing.stat().st_size > 50_000:
        return existing
    out = wd / "video.mp4"
    for u in urls:
        try:
            req = urllib.request.Request(u, headers={
                "User-Agent": UA,
                "Referer": "https://www.douyin.com/",
                "Cookie": ck(),
            })
            with urllib.request.urlopen(req, timeout=timeout) as r, open(out, "wb") as f:
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
    out = wd / "audio.wav"
    if out.exists() and out.stat().st_size > 10_000:
        return out
    cmd = [str(FFMPEG), "-y", "-i", str(video_file), "-vn", "-ac", "1", "-ar", "16000", str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 10_000:
            return out
    except Exception:
        pass
    return None


def probe_video_stream(video_file: Path) -> bool:
    """文件是否含**视频流**。抖音有些"视频"其实是纯音频（M4A，只有 Audio 流），
    抽帧必然失败——这不是错误，应打标记跳过（坑位 AG）。"""
    cmd = [str(FFMPEG), "-i", str(video_file), "-hide_banner"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return bool(re.search(r"Stream #\d+:\d+.*: Video:", r.stderr))
    except Exception:
        return True   # 探测不了就当作有视频流，按原流程试


def extract_frames(video_file: Path, wd: Path, duration: float):
    if duration and duration > 600:
        step = 120
        times = list(range(step // 2, int(duration), step))[:12]
    else:
        fracs = [0.25, 0.55, 0.85]
        times = [max(1.0, duration * f) if duration else (i + 1) * 30 for i, f in enumerate(fracs)]
    frames = []
    for i, t in enumerate(times):
        out = wd / f"kf_{int(t):05d}.jpg"
        if out.exists() and out.stat().st_size > 1000:
            frames.append({"path": str(out), "t": int(t)})
            continue
        cmd = [str(FFMPEG), "-y", "-ss", f"{float(t):.1f}", "-i", str(video_file),
               "-frames:v", "1", "-q:v", "3", str(out)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if r.returncode == 0 and out.exists() and out.stat().st_size > 1000:
                frames.append({"path": str(out), "t": int(t)})
        except Exception:
            pass
    return frames


def probe_duration(video_file: Path):
    """用 ffmpeg 读时长（转写失败但想要帧时用）"""
    cmd = [str(FFMPEG), "-i", str(video_file), "-hide_banner"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r.stderr)
        if m:
            h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            return h * 3600 + mi * 60 + s
    except Exception:
        pass
    return 0.0


_whisper = None


def get_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        local = ROOT / "models" / "faster-whisper-small"
        model_id = str(local) if (local / "model.bin").exists() else WHISPER_MODEL
        if not model_id.startswith(str(ROOT)):
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        log(f"  加载 whisper 模型（{model_id}）…")
        _whisper = WhisperModel(model_id, device="cpu", compute_type="int8")
    return _whisper


def transcribe(audio: Path):
    model = get_whisper()
    segments, info = model.transcribe(str(audio), language="zh", vad_filter=True)
    lines, plain = [], []
    for seg in segments:
        lines.append(f"[{ts(seg.start)}] {seg.text.strip()}")
        plain.append(seg.text.strip())
    return "\n".join(lines), "".join(plain), info.duration or 0


def split_candidates(transcript_text: str):
    """把逐字稿切成候选句。

    ⚠ 坑位 U（2026-10-10 实测）：whisper 输出的中文逐字稿**经常整篇没有一个标点**
      （每行 [mm:ss] 短语，行尾无句读）。按 [。！？；] 切只得 1 段、逗号级联也只得 1 段
      → 要点恒为空。所以要做多级兜底。

    ⚠ 坑位 AC（2026-10-10 二次踩）：调用方有时传进来的是 `plain`
      （whisper 各段 text **直接拼接**、既无时间戳也**无换行**），这时「按行切」也失效
      → 仍只剩 1 段。所以最后一级兜底必须是**按固定长度滑窗切块**，不依赖任何分隔符。

    兜底顺序：
      ① 句读 [。！？!?；;]  →  ② 逗号级联 [。！？!?；;，,、]
      →  ③ 按时间戳行边界（有 [mm:ss] 前缀时）
      →  ④ 固定长度滑窗（16~28 字一窗，带 50% 重叠）—— 不依赖任何标点/换行
    """
    text = re.sub(r"\s+", "", transcript_text)
    if not text:
        return []
    sents = [s for s in re.split(r"[。！？!?；;]", text) if len(s) >= 8]
    if len(sents) < 2:
        sents = [s for s in re.split(r"[。！？!?；;，,、]", text) if len(s) >= 8] or sents
    if len(sents) < 2 or all(len(s) > 120 for s in sents):
        # ③ 按行（时间戳行）切：去掉 [mm:ss] 前缀后逐行累积到 ≥12 字
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
        # ④ 固定长度滑窗（最后兜底，不依赖标点/换行）
        #    ⚠ 判据要含「所有候选都 >120 字」：有些长稿只有 2~3 个句号，
        #      切出来是 2~3 个「巨块」，clean_points 会因 >200 字整条丢弃 → 要点为空。
        win, step = 22, 11
        if len(text) >= win:
            sents = [text[i:i + win] for i in range(0, len(text) - win + 1, step)]
        else:
            sents = [text]
    return sents


def summarize_points(transcript_text: str, title: str, max_points: int = 3):
    """规则式要点兜底；一律过 clean_points 同一道闸门（坑位 H/O）。

    打分口径（坑位 U 补丁）：
      关键词 2 分/个、含数字 1 分；另外「长度 14~60 字」给 1 分偏好分
      —— 短碎片（<14）信息量低、超长串（>60）不适合做要点，都不该被优先选。
      若全篇无任何关键词命中，偏好分能避免随机挑到「对是然后你完成了」这种碎片。
    """
    sents = split_candidates(transcript_text)
    if not sents:
        return []
    key = ["首先", "然后", "其次", "最后", "注意", "关键", "重点", "第一", "第二", "第三",
           "建议", "一定", "不要", "切记", "核心", "原理", "方法", "步骤",
           "方法", "可以", "怎么", "为什么", "因为", "所以", "结果", "案例", "数据", "收入"]
    scored = []
    for idx, s in enumerate(sents):
        sc = sum(2 for k in key if k in s)
        sc += 1 if re.search(r"\d", s) else 0
        sc += 1 if 14 <= len(s) <= 60 else 0
        # 轻微偏早（开头通常是主题陈述），但幅度小于内容分
        sc -= idx * 0.01
        scored.append((sc, s))
    scored.sort(key=lambda x: -x[0])
    return clean_points([s for _, s in scored[: max_points * 4]], max_n=max_points)


# ---------------- Playwright 直链刷新 ----------------

class UrlRefresher:
    """复用同一个浏览器上下文，按需为某条视频拿新鲜直链"""

    def __init__(self):
        self._pw = None
        self._ctx = None
        self._page = None

    def start(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            str(PROFILE), headless=False,
            viewport={"width": 1380, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def fetch(self, vid: str, timeout_ms=25000):
        found = []

        def on_resp(resp):
            try:
                if "/aweme/v1/web/aweme/detail/" in resp.url:
                    aw = (resp.json().get("aweme_detail") or {})
                    pl = ((aw.get("video") or {}).get("play_addr") or {}).get("url_list") or []
                    for u in pl:
                        if u not in found:
                            found.append(u)
            except Exception:
                pass

        page = self._page
        page.on("response", on_resp)
        try:
            page.goto(f"https://www.douyin.com/video/{vid}",
                      wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(3500)
        except Exception:
            pass
        try:
            page.remove_listener("response", on_resp)
        except Exception:
            pass
        return found

    def stop(self):
        try:
            if self._ctx:
                self._ctx.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass


def main():
    if not acquire("batch_transcribe"):
        return
    try:
        _main()
    finally:
        release()

def _main():
    limit = 0            # 0 = 不限
    only_ids = None
    frames_only = False
    refresh = True
    args = sys.argv[1:]
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    if "--only-ids" in args:
        only_ids = set(args[args.index("--only-ids") + 1].split(","))
    if "--frames-only" in args:
        frames_only = True
    if "--no-refresh" in args:
        refresh = False

    if not COOKIES_FILE.exists():
        log("缺少 data/cookies.txt")
        return

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    # ---- 选任务 ----
    todo = []       # (v, folder_name, kind)  kind: 'full' | 'frames'
    for f in data.get("folders", []):
        for v in f.get("videos", []):
            vid = str(v["id"])
            if only_ids and vid not in only_ids:
                continue
            if frames_only:
                # 只补帧：豁免条目（或有 transcript 的条目）缺 frames
                if (v.get("no_transcript") or v.get("transcript")) and \
                        not (v.get("frames") or []) and not v.get("no_frames"):
                    todo.append((v, f.get("name", ""), "frames"))
                continue
            if v.get("transcript") or v.get("no_transcript"):
                continue
            if v.get("dl_failed_recently") and not only_ids:
                # 上一轮失败过的，仍允许重试（直链会刷新），但排在后面
                todo.append((v, f.get("name", ""), "retry"))
            else:
                todo.append((v, f.get("name", ""), "full"))

    # 优先 full，其次 retry，最后 frames
    order = {"full": 0, "retry": 1, "frames": 2}
    todo.sort(key=lambda x: order.get(x[2], 9))
    total_pending = len(todo)
    if limit:
        todo = todo[:limit]
    if not todo:
        log("没有待处理视频。")
        return

    log(f"待处理 {total_pending} 条，本批 {len(todo)} 条"
        f"（full {sum(1 for t in todo if t[2]=='full')} / retry {sum(1 for t in todo if t[2]=='retry')} / frames {sum(1 for t in todo if t[2]=='frames')}）")

    refresher = None
    done = failed = no_speech = 0
    skipped_frames = 0
    t0 = time.time()

    def save():
        # ⚠ 坑位 AF：必须**原子写**。旧实现直接 write_text 36MB 到目标文件，
        #   主批每处理一条写一次 → 并发读者（测试/巡检/收尾链）约 40% 概率读到半截 JSON
        #   （实测 12 次采样 5 次 JSONDecodeError），且中途崩溃会把文件写坏。
        #   改为「写临时文件 → os.replace 原子替换」：读者要么看到旧版要么看到新版，永不撕裂。
        # ⚠ 坑位 AF-2：Windows 下若目标文件正被别的进程打开（并发读者/杀软扫描），
        #   os.replace 会抛 WinError 5（拒绝访问）→ 该条被记为失败。**必须重试**（短暂退避），
        #   实测单次重试即可恢复；仍失败则退化为「重写临时名」并在下一条再试。
        # ⚠ 坑位 AF-3：临时文件名必须带 **PID**。若两个 batch 进程（或崩溃残留进程）共用
        #   同一个 `favorites.json.tmp`，会互相截断/争用 → 触发 WinError 5 或写出损坏内容。
        #   带 PID 后各进程写各自的 tmp，再各自 os.replace，互不干扰。
        tmp = DATA_FILE.with_suffix(f".{os.getpid()}.json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        delay = 0.2
        for attempt in range(8):
            try:
                os.replace(tmp, DATA_FILE)
                return
            except PermissionError:
                time.sleep(delay)
                delay = min(delay * 2, 2.0)
        # 最后兜底：再写一次临时文件并重试一次（仍失败则抛出，由上层记为该条异常）
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, DATA_FILE)

    for i, (v, fname, kind) in enumerate(todo, 1):
        vid = str(v["id"])
        wd = MEDIA_DIR / vid
        wd.mkdir(parents=True, exist_ok=True)
        title = v.get("title", "")[:38]
        log(f"[{i}/{len(todo)}] ({kind}) {title} ({vid})")
        try:
            vf = wd / "video.mp4"
            if not (vf.exists() and vf.stat().st_size > 50_000):
                urls = v.get("play_urls") or []
                vf = download_video(urls, wd)
                if not vf and refresh:
                    # 直链过期 → Playwright 刷新
                    if refresher is None:
                        log("  启动浏览器刷新直链…")
                        refresher = UrlRefresher()
                        refresher.start()
                    fresh = refresher.fetch(vid)
                    if fresh:
                        v["play_urls"] = fresh
                        save()
                        vf = download_video(fresh, wd)
                    else:
                        log("  !! 未捕获到新直链")
                if not vf:
                    v["dl_failed_recently"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    failed += 1
                    save()
                    continue

            if kind == "frames":
                # ⚠ 坑位 AG：纯音频文件（M4A，无 Video 流）抽帧必然失败，不是错误。
                #   抖音「纯 BGM 图文帖」下载下来就是音频，标 no_frames 跳过，别再反复重试。
                if not probe_video_stream(vf):
                    v["no_frames"] = "audio_only_no_video_stream"
                    v["processed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    skipped_frames += 1
                    save()
                    log("  ⏭ 纯音频（无视频流），跳过抽帧")
                    continue
                dur = probe_duration(vf)
                fr_list = extract_frames(vf, wd, dur)
                if fr_list:
                    v["frames"] = [{"url": f["path"], "t": f["t"],
                                    "cap": f"{f['t'] // 60}:{f['t'] % 60:02d}"} for f in fr_list]
                    v["processed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    done += 1
                    save()
                    log(f"  ✅ 补齐关键帧 {len(fr_list)} 张（时长 {dur:.0f}s）")
                else:
                    failed += 1
                    log("  !! 抽帧失败")
                continue

            audio = extract_audio(vf, wd)
            if not audio:
                v["dl_failed_recently"] = time.strftime("%Y-%m-%d %H:%M:%S")
                failed += 1
                save()
                log("  !! 音频提取失败")
                continue
            stamp_text, plain, dur = transcribe(audio)
            # ⚠ 坑位 X：whisper 在无中文语音时会「硬凑」出英文幻觉（如 "That's me"）。
            #   判据：中文字符占比 < 30% 且总字数 < 40 → 视为无有效语音，打豁免。
            # ⚠ 坑位 AA：水印署名（「字幕by索兰娅」）或去标点后 <8 实字 → 也是无有效语音。
            zh_n = len(re.findall(r"[\u4e00-\u9fff]", plain))
            if not plain or (len(plain) < 40 and zh_n / max(1, len(plain)) < 0.30) \
                    or is_fake_transcript(stamp_text):
                # 无语音：打豁免 + 仍要帧
                v["no_transcript"] = "no_speech_whisper_empty"
                fr_list = extract_frames(vf, wd, dur or probe_duration(vf))
                if fr_list:
                    v["frames"] = [{"url": f["path"], "t": f["t"],
                                    "cap": f"{f['t'] // 60}:{f['t'] % 60:02d}"} for f in fr_list]
                v.pop("dl_failed_recently", None)
                v["processed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                no_speech += 1
                save()
                log(f"  ⚠ 无有效语音（原始 {len(plain)} 字 / 中文 {zh_n} 字），已打豁免 + 截图 {len(fr_list)} 张")
                continue
            v["transcript"] = stamp_text
            v["points"] = summarize_points(plain, v.get("title", ""))
            fr_list = extract_frames(vf, wd, dur)
            v["frames"] = [{"url": f["path"], "t": f["t"],
                            "cap": f"{f['t'] // 60}:{f['t'] % 60:02d}"} for f in fr_list]
            v["processed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            v.pop("dl_failed_recently", None)
            done += 1
            save()
            log(f"  ✅ {len(plain)} 字，要点 {len(v['points'])} 条，截图 {len(fr_list)} 张，"
                f"累计 {time.time() - t0:.0f}s")
        except Exception as e:
            failed += 1
            log(f"  !! 异常：{type(e).__name__}: {e}")

    if refresher:
        refresher.stop()

    # ★ 自愈：整批结束后，把所有「有逐字稿但要点为空 / 要点不合规」的条目重新过一遍闸门。
    #   这样即使本进程运行的是旧版 summarize_points（坑位 AB），落盘数据也一定合规。
    healed = 0
    for f in data.get("folders", []):
        for v in f.get("videos", []):
            tr = v.get("transcript")
            if not tr:
                continue
            cur = clean_points(v.get("points") or [], max_n=3)
            if cur:
                if cur != (v.get("points") or []):
                    v["points"] = cur
                    healed += 1
                continue
            new_pts = summarize_points(tr, v.get("title", ""))
            if new_pts:
                v["points"] = new_pts
                healed += 1
    if healed:
        save()
        log(f"要点自愈：重算 {healed} 条")

    log(f"\n批次完成：成功 {done} / 无语音豁免 {no_speech} / 纯音频跳过抽帧 {skipped_frames} / "
        f"失败 {failed} / 共 {len(todo)}，耗时 {time.time() - t0:.0f}s")
    log(f"剩余待处理约 {total_pending - len(todo)} 条（下次续跑）")


if __name__ == "__main__":
    main()
