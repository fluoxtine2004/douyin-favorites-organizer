# -*- coding: utf-8 -*-
"""
清理“伪转写”：whisper 把屏幕上的字幕署名水印（如“字幕by索兰娅”）或极短口播误识别成转写，
导致网页出现空卡片。把这些视频在 favorites.json / enriched.json 中统一标记为 no_transcript。
"""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAV = ROOT / "data" / "favorites.json"
ENR = ROOT / "data" / "enriched.json"

WATERMARK = re.compile(r"字幕\s*by|@[\u4e00-\u9fff]+字幕|听译|机翻|翻译by|subtitle by", re.I)
TS = re.compile(r"\[\d{1,2}:\d{2}(?::\d{2})?\]")
PUNCT = re.compile(r"[\s，。、！？…—,.\!\?~\"'：:；;（）()\[\]【】\-\u3000]")

def real_len(t):
    s = TS.sub("", t)
    return len(s) - len(PUNCT.findall(s))

def is_fake(t):
    if not t or not t.strip():
        return False
    if WATERMARK.search(t):
        return True
    return real_len(t) <= 8

fav = json.loads(FAV.read_text(encoding="utf-8"))
enr = json.loads(ENR.read_text(encoding="utf-8"))

fake_ids = []
for f in fav.get("folders", []):
    for v in f.get("videos", []):
        t = (v.get("transcript") or "").strip()
        if is_fake(t):
            fake_ids.append(v["id"])

print(f"命中伪转写：{len(fake_ids)} 条")

# 1) favorites.json：清空 transcript，标记 no_transcript
fcount = 0
for f in fav.get("folders", []):
    for v in f.get("videos", []):
        if v["id"] in fake_ids:
            v["transcript"] = ""
            v["no_transcript"] = "no_audio_or_bgm"
            v.pop("points", None)   # 伪转写没有可靠要点
            fcount += 1
FAV.write_text(json.dumps(fav, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"favorites.json 已清理 {fcount} 条")

# 2) enriched.json：把 has_transcript 置否，清空派生内容
ecount = 0
for i in fake_ids:
    if i in enr:
        e = enr[i]
        e["has_transcript"] = False
        e["summary"] = ""
        e["points"] = []
        e["segments"] = []
        e.pop("transcript", None)
        ecount += 1
ENR.write_text(json.dumps(enr, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"enriched.json 已修正 {ecount} 条")

print("完成。建议重新运行 build_dashboard.py 与 build_site.py。")
