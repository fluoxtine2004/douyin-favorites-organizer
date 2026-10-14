# -*- coding: utf-8 -*-
"""
恢复脚本：clean_fake_notes.py 误给“有真实转写”的笔记在逐字稿段尾插入了
“本视频无语音内容…”占位行。本脚本据 favorites.json 的真实 transcript 判断：
  - 视频有真实转写 -> 删除该占位行
  - 视频确无语音(no_transcript 或 transcript 过短) -> 保留占位行
仅删除精确匹配的那一行，不动其余内容。
"""
import json, re, glob
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / "vault"
PLACE = "本视频无语音内容（纯音乐 / 画面为主），无逐字稿。"

fav = json.load(open(ROOT / "data" / "favorites.json", encoding="utf-8"))
allv = {}
for f in fav.get("folders", []):
    for v in f.get("videos", []):
        allv[v["id"]] = v

TS = re.compile(r"\[\d{1,2}:\d{2}(?::\d{2})?\]")
PUNCT = re.compile(r"[\s，。、！？…—,.\!\?~\"'：:；;（）()\[\]【】\-\u3000]")
def real_len(t):
    s = TS.sub("", t); return len(s) - len(PUNCT.findall(s))

real_ids = set()
for vid, v in allv.items():
    tr = (v.get("transcript") or "").strip()
    if tr and real_len(tr) > 15:
        real_ids.add(vid)
print(f"有真实转写的视频数: {len(real_ids)}")

removed = kept = 0
for fp in glob.glob(str(VAULT / "**" / "*.md"), recursive=True):
    if fp.endswith("README.md"):
        continue
    t = open(fp, encoding="utf-8").read()
    m = re.search(r"/video/(\d+)", t)
    vid = m.group(1) if m else None
    if vid in real_ids and PLACE in t:
        new_lines = [ln for ln in t.splitlines() if ln.strip() != ("> " + PLACE)]
        if len(new_lines) != len(t.splitlines()):
            open(fp, "w", encoding="utf-8").write("\n".join(new_lines))
            removed += 1
    elif vid not in real_ids and PLACE in t:
        kept += 1

print(f"已删除误加占位行的笔记: {removed} 篇")
print(f"保留占位行(确无语音)的笔记: {kept} 篇")
