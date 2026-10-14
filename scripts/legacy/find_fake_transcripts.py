# -*- coding: utf-8 -*-
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "favorites.json"
d = json.loads(DATA.read_text(encoding="utf-8"))

# 伪转写特征：
# 1) 含字幕水印署名 / 制作 credits（whisper 把屏幕上或音频里的“字幕byXXX”“MING PAO”当语音识别）
# 2) 乱码：同一短子串大量重复（如 BITBITBIT…）
# 3) 去掉时间戳和标点后，纯中文/字符极少（<=8 字）且不含正常句子
WATERMARK = re.compile(
    r"字幕\s*by|字幕组|@[\u4e00-\u9fff]+字幕|听译|机翻|翻译\s*by|subtitle|субтитр|"
    r"詞曲|作曲|编曲|演唱\s*[:：]|出品|MING\s*PAO|EDITOR|CREDIT|时间轴|校对",
    re.I)
TS = re.compile(r"\[\d{1,2}:\d{2}\]|\[\d{1,2}:\d{2}:\d{2}\]")
PUNCT = re.compile(r"[\s，。、！？…—,.\!\?~\"'：:；;（）()\[\]【】\-\u3000]")

def real_len(t):
    return len(TS.sub("", t)) - len(PUNCT.findall(TS.sub("", t)))

def is_gibberish(t):
    for L in (2, 3, 4):
        c = {}
        for i in range(len(t) - L + 1):
            sub = t[i:i + L]
            c[sub] = c.get(sub, 0) + 1
        if c:
            top, cnt = max(c.items(), key=lambda kv: kv[1])
            if cnt >= 10 and cnt * L > 0.5 * len(t):
                return True
    return False

fake = []
for f in d.get("folders", []):
    for v in f.get("videos", []):
        t = (v.get("transcript") or "").strip()
        if not t:
            continue
        if WATERMARK.search(t):
            fake.append((v["id"], f.get("name"), v.get("title",""), "watermark", t[:40]))
            continue
        if is_gibberish(TS.sub("", t)):
            fake.append((v["id"], f.get("name"), v.get("title",""), "gibberish", t[:40]))
            continue
        rl = real_len(t)
        if rl <= 8:
            fake.append((v["id"], f.get("name"), v.get("title",""), f"too_short({rl})", t[:40]))

print(f"疑似伪转写视频数：{len(fake)}")
for fid, folder, title, why, snippet in fake:
    print(f"  [{why}] {fid} | {folder} | {title[:24]} | {snippet!r}")

# 也扫描 enriched 是否同样需清理
enr = ROOT / "data" / "enriched.json"
e = json.loads(enr.read_text(encoding="utf-8"))
efake = [k for k,v in e.items() if v.get("transcript") and WATERMARK.search(v["transcript"])]
print(f"enriched 含水印伪转写：{len(efake)}")
