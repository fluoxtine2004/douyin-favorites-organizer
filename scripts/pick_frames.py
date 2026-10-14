# -*- coding: utf-8 -*-
"""
智能选帧：只挑「有信息量」的画面（画面切换 / 图表·文字页 / 与重要口播对齐的时刻）
方法：
  1) ffmpeg 场景切换检测（select='gt(scene,x)' + showinfo）→ 候选时间点及切换强度
  2) 逐字稿重要句锚定：对含数字/关键词（第一/重点/步骤/建议/结论/数据…）的口播时刻加权
  3) 去重 + 间隔约束（≥25s）后取 Top N（短 3-5 帧，长视频最多 8 帧）
  4) 抽帧并写回 favorites.json（frames: url/t/cap，cap 说明为什么选这一帧）
用法：
  python pick_frames.py [--limit 30] [--ids id1,id2] [--only-transcribed] [--all]
"""
import json
import re
import sys as _sys
_sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from lockutil import acquire, release  # noqa
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "favorites.json"
MEDIA = ROOT / "media"
COOKIES = ROOT / "data" / "cookies.txt"
from ffmpegutil import get_ffmpeg  # noqa: E402

FFMPEG = get_ffmpeg()
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
KEY = re.compile(r"(第一|第二|第三|首先|其次|最后|重点|关键|核心|结论|建议|方法|步骤|原理|注意|"
                 r"数据|增长|收入|成本|结果|对比|区别|为什么|如何|总结|记住)")


def log(m):
    print(m, flush=True)


def cookie_header() -> str:
    pairs = []
    for line in COOKIES.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) == 7:
            pairs.append(p[5] + "=" + p[6])
    return "; ".join(pairs)


def ensure_video(v, wd: Path):
    out = wd / "video.mp4"
    if out.exists() and out.stat().st_size > 50_000:
        return out
    for u in (v.get("play_urls") or []):
        try:
            req = urllib.request.Request(u, headers={
                "User-Agent": UA, "Referer": "https://www.douyin.com/", "Cookie": cookie_header()})
            with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as f:
                while True:
                    c = r.read(1 << 18)
                    if not c:
                        break
                    f.write(c)
            if out.stat().st_size > 50_000:
                return out
        except Exception:
            continue
    if out.exists():
        try:
            out.unlink()
        except Exception:
            pass
    return None


def scene_candidates(video: Path, threshold=0.22):
    """场景切换检测，返回 [(t, 强度)]"""
    cmd = [str(FFMPEG), "-i", str(video), "-filter:v",
           f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception:
        return []
    txt = (r.stderr or "") + (r.stdout or "")
    out = []
    for m in re.finditer(r"pts_time:([\d.]+)(?:.*?mean:\[[\d.]+ [\d.]+ [\d.]+ [\d.]+ ([0-9.eE+-]+)\])?", txt):
        t = float(m.group(1))
        sc = float(m.group(2)) if m.group(2) else 0.0
        out.append((t, sc))
    return out


def parse_duration(d) -> int:
    try:
        parts = [int(x) for x in str(d).split(":")]
    except Exception:
        return 0
    s = 0
    for p in parts:
        s = s * 60 + p
    return s


def segments_of(v):
    segs = []
    for line in (v.get("transcript") or "").splitlines():
        m = re.match(r"\[(\d+):(\d+)\]\s*(.+)", line.strip())
        if m:
            segs.append({"t": int(m.group(1)) * 60 + int(m.group(2)), "text": m.group(3)})
    return segs


def pick(v, dur: int, segs):
    """返回 [(t, 理由)]"""
    cands = scene_candidates(MEDIA / v["id"] / "video.mp4")
    scored = {}   # t(取整到5秒) -> [score, reason]

    def add(t, s, why):
        key = int(t // 5) * 5
        if key not in scored or s > scored[key][0]:
            scored[key] = [s, why]

    if cands:
        mx = max((sc for _, sc in cands), default=1.0) or 1.0
        for t, sc in cands:
            add(t, 1.0 + 3.0 * (sc / mx), "画面切换/版式变化")
    # 逐字稿重要句锚定
    for s in segs:
        txt = s["text"]
        hits = len(KEY.findall(txt)) + len(re.findall(r"\d", txt))
        if hits >= 2 and len(txt) >= 8:
            add(s["t"], 4.0 + hits, "关键口播：" + txt[:22])
    # 兜底：均匀候选
    if not scored:
        for i in range(1, 4):
            add(dur * i / 4 if dur else i * 30, 1.0, "均匀取样")
    # 按分数排序，做间隔约束
    items = sorted(scored.items(), key=lambda kv: -kv[1][0])
    max_n = 8 if dur > 600 else (5 if dur > 180 else 3)
    picked = []
    for t, (s, why) in items:
        if any(abs(t - p[0]) < 25 for p in picked):
            continue
        picked.append((t, why))
        if len(picked) >= max_n:
            break
    picked.sort(key=lambda x: x[0])
    return picked


def main():
    if not acquire("pick_frames"):
        return
    limit = None
    ids = None
    only_trans = "--only-transcribed" in sys.argv
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    if "--ids" in sys.argv:
        ids = set(sys.argv[sys.argv.index("--ids") + 1].split(","))

    data = json.loads(DATA.read_text(encoding="utf-8"))
    todo = []
    for f in data.get("folders", []):
        for v in f.get("videos", []):
            if ids and v["id"] not in ids:
                continue
            if only_trans and not v.get("transcript"):
                continue
            if v.get("frames_curated"):
                continue
            todo.append(v)
    if limit:
        todo = todo[:limit]
    log(f"选帧任务：{len(todo)} 条")
    done = 0
    for i, v in enumerate(todo, 1):
        wd = MEDIA / v["id"]
        wd.mkdir(parents=True, exist_ok=True)
        dur = parse_duration(v.get("duration", ""))
        try:
            vf = ensure_video(v, wd)
            if not vf:
                log(f"[{i}/{len(todo)}] 跳过（无视频文件）：{v['title'][:26]}")
                continue
            segs = segments_of(v)
            picks = pick(v, dur, segs)
            frames = []
            for j, (t, why) in enumerate(picks):
                out = wd / f"kf_{int(t):05d}.jpg"
                r = subprocess.run([str(FFMPEG), "-y", "-ss", f"{t:.1f}", "-i", str(vf),
                                    "-frames:v", "1", "-q:v", "3", str(out)],
                                   capture_output=True, text=True, timeout=120)
                if r.returncode == 0 and out.exists():
                    frames.append({"url": str(out), "t": int(t),
                                   "cap": f"{why}" + (f"（{int(t)//60}:{int(t)%60:02d}）" if dur else "")})
            if frames:
                # 旧帧文件保留（新帧为 kf_*.jpg，避免触发批量删除保护）
                v["frames"] = frames
                v["frames_curated"] = time.strftime("%Y-%m-%d %H:%M:%S")
                done += 1
                log(f"[{i}/{len(todo)}] ✅ {v['title'][:26]} → {len(frames)} 帧（{'; '.join(f['cap'][:12] for f in frames)}）")
            else:
                log(f"[{i}/{len(todo)}] ⚠ 未能选帧：{v['title'][:26]}")
            DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            log(f"[{i}/{len(todo)}] !! 失败：{e}")
    log(f"选帧完成：{done}/{len(todo)}")


    release()


if __name__ == "__main__":
    main()
