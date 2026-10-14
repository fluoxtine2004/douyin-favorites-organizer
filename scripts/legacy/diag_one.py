# -*- coding: utf-8 -*-
"""诊断单条视频的下载→音频→转写链路，打印每一步真实异常"""
import json, sys, traceback
from pathlib import Path
sys.path.insert(0, str(Path(r"\scripts")))
import process_batch as pb

ROOT = Path(__file__).resolve().parents[1]
d = json.loads((ROOT / "data" / "favorites.json").read_text(encoding="utf-8"))
ids = json.loads((ROOT / "data" / "_retry_ids.json").read_text(encoding="utf-8"))
rec = {}
for f in d["folders"]:
    for v in f["videos"]:
        if v["id"] in ids:
            rec[v["id"]] = v

i = ids[0]
v = rec[i]
wd = ROOT / "media" / i
wd.mkdir(parents=True, exist_ok=True)
print("== 视频:", i, v.get("title", "")[:40])
print("play_urls:", len(v.get("play_urls") or []))

# 1) 下载（先删缓存，强制重新下载，排除缓存损坏）
cf = wd / "video.mp4"
if cf.exists():
    print("删除旧缓存 video.mp4 (size=%d)" % cf.stat().st_size)
    cf.unlink()
try:
    vf = pb.download_video(v, wd)
    print("download_video ->", vf, "exists=", vf.exists() if vf else False,
          "size=", vf.stat().st_size if (vf and vf.exists()) else 0)
except Exception as e:
    print("!! download_video 异常:", repr(e))
    traceback.print_exc()
    sys.exit(1)

try:
    au = pb.extract_audio(vf, wd)
    print("extract_audio ->", au, "exists=", au.exists() if au else False,
          "size=", au.stat().st_size if (au and au.exists()) else 0)
except Exception as e:
    print("!! extract_audio 异常:", repr(e))
    traceback.print_exc()
    sys.exit(1)

try:
    st, pl, dur = pb.transcribe(au)
    print("transcribe -> dur=%.1f plain_len=%d" % (dur, len(pl)))
    print("plain 前80字:", pl[:80])
except Exception as e:
    print("!! transcribe 异常:", repr(e))
    traceback.print_exc()
    sys.exit(1)
print("OK")
