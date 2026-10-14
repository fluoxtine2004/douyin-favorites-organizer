# -*- coding: utf-8 -*-
"""
清理 favorites.json 中的【真·伪转写】：仅当整段转写被水印/字幕署名/credits/乱码主导（>=50%）才清空。
高精度：只匹配强水印信号（字幕by / 字幕组 / 听译 / 机翻 / subtitle / субтитр / MING PAO），
排除 时间轴/词曲/演唱/editor/credit 等正常口语词，避免误伤真实中文/英文逐字稿。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "favorites.json"

# 强水印/credits 信号（高精度，几乎不可能出现在正常口语里）
STRONG_WM = re.compile(
    r"字幕\s*by|字幕组|@[\u4e00-\u9fff]+字幕|听译|机翻|翻译\s*by|subtitle|субтитр|MING\s*PAO",
    re.I)
TS = re.compile(r"\[\d{1,2}:\d{2}\]|\[\d{1,2}:\d{2}:\d{2}\]")


def is_gibberish(text):
    for L in (2, 3, 4):
        c = {}
        for i in range(len(text) - L + 1):
            sub = text[i:i + L]
            c[sub] = c.get(sub, 0) + 1
        if c:
            top, cnt = max(c.items(), key=lambda kv: kv[1])
            if cnt >= 10 and cnt * L > 0.5 * len(text):
                return True
    return False


def line_bad(line):
    if STRONG_WM.search(line):
        return True
    if is_gibberish(line):
        return True
    return False


def fake_ratio(transcript):
    """返回 (是否伪转写, 占比, 命中行数/总行数)"""
    lines = [TS.sub("", ln).strip() for ln in transcript.splitlines() if TS.sub("", ln).strip()]
    if not lines:
        return False, 0.0, (0, 0)
    total = sum(len(ln) for ln in lines)
    bad = sum(len(ln) for ln in lines if line_bad(ln))
    ratio = (bad / total) if total else 0.0
    return ratio >= 0.5, ratio, (sum(1 for ln in lines if line_bad(ln)), len(lines))


def main():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    cleared = []
    for f in d.get("folders", []):
        for v in f.get("videos", []):
            t = (v.get("transcript") or "").strip()
            if not t:
                continue
            bad, ratio, (nb, nt) = fake_ratio(t)
            if bad:
                cleared.append((v["id"], f.get("name"), v.get("title", "")[:22], round(ratio, 2), t[:34]))
                v["transcript"] = ""
                v["points"] = []
                v["frames"] = []
                v["no_transcript"] = "no_audio_or_bgm"
                v.pop("processed_at", None)
    DATA.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"清理真·伪转写：{len(cleared)} 条")
    for cid, folder, title, ratio, snip in cleared:
        print(f"  [CLEAR r={ratio}] {cid} | {folder} | {title} | {snip!r}")


if __name__ == "__main__":
    main()
