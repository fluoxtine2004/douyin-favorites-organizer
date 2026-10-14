# -*- coding: utf-8 -*-
import json, re, glob
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
fav = json.load(open(ROOT / "data" / "favorites.json", encoding="utf-8"))
allv = {}
for f in fav.get("folders", []):
    for v in f.get("videos", []):
        allv[v["id"]] = v
TS = re.compile(r"\[\d{1,2}:\d{2}(?::\d{2})?\]")
PUNCT = re.compile(r"[\s，。、！？…—,.\!\?~\"'：:；;（）()\[\]【】\-\u3000]")
def rl(t):
    s = TS.sub("", t); return len(s) - len(PUNCT.findall(s))
real = set(i for i, v in allv.items() if (v.get("transcript") or "").strip() and rl(v["transcript"]) > 15)
PLACE = "本视频无语音内容（纯音乐 / 画面为主），无逐字稿。"
suspect = 0
samples = []
for fp in glob.glob(str(ROOT / "vault" / "**" / "*.md"), recursive=True):
    if fp.endswith("README.md"):
        continue
    t = open(fp, encoding="utf-8").read()
    if PLACE not in t:
        continue
    m = re.search(r"/video/(\d+)", t)
    vid = m.group(1) if m else None
    if vid is None or vid in real:
        suspect += 1
        if len(samples) < 10:
            samples.append((fp.split("\\")[-1][:42], vid, vid in real))
print("需二次清理的笔记:", suspect)
for s in samples:
    print("  ", s)
