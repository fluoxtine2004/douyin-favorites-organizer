# -*- coding: utf-8 -*-
"""对 9 条确认是否真无声：重新下载+抽取音频，多配置转写取最长，输出每条长度，不写 favorites"""
import json, sys
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

model = pb.get_whisper()
results = {}
for i in ids:
    v = rec[i]
    wd = ROOT / "media" / i
    wd.mkdir(parents=True, exist_ok=True)
    cf = wd / "video.mp4"
    if cf.exists():
        cf.unlink()
    vf = pb.download_video(v, wd)
    if not vf:
        results[i] = ("DL_FAIL", 0, "")
        continue
    au = pb.extract_audio(vf, wd)
    if not au:
        results[i] = ("AUDIO_FAIL", 0, "")
        continue
    best = ("", 0, "")
    for lang in ("zh", None, "en"):
        try:
            segs, info = model.transcribe(str(au), language=lang, vad_filter=False)
            t = "".join(s.text for s in segs).strip()
            if len(t) > best[1]:
                best = (lang, len(t), t[:80])
        except Exception as e:
            pass
    results[i] = (best[0], best[1], best[2])
    print(f"{i} lang={best[0]} len={best[1]} :: {best[2]!r}")

print("\n== 汇总 ==")
speech = [i for i, r in results.items() if r[1] >= 15]
silent = [i for i, r in results.items() if r[1] < 15]
print("疑似有语音(>=15字):", len(speech), speech)
print("判定无声(<15字):", len(silent), silent)
