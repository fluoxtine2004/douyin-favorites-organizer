# -*- coding: utf-8 -*-
"""
保守补齐 enriched.json：
  - 只为「缺失」或「has_transcript 状态与 favorites.json 不一致」的视频重建条目
  - 已有条目原样保留（避免丢掉已写入 enriched 的 AI 精修 summary / points）
用法：python refill_enriched.py [--dry]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "favorites.json"
ENR = ROOT / "data" / "enriched.json"
LLM_NOTES = ROOT / "data" / "llm_notes.json"
sys.path.insert(0, str(ROOT / "scripts"))
import enrich as E  # noqa: E402

DRY = "--dry" in sys.argv


def build_entry(v, note):
    """与 enrich.main() 中单条逻辑保持一致"""
    dur = E.parse_duration(v.get("duration", ""))
    raw = E.raw_segments(v.get("transcript", ""))
    segs = E.polish_segments(raw)
    if note.get("condensed"):
        segs = [{"t": int(s.get("t", 0)), "text": E.t2s(s.get("text", ""))}
                for s in note["condensed"]]
    summary = note.get("summary") or E.make_summary(segs)
    # ⚠ 不要沿用 v.get("points")（favorites.json 里是整篇文稿拼接）。
    #    优先 llm_notes，其次按整理后的分段现算 2~3 句，最后统一过字数护栏。
    points = E.clean_points(note.get("points") or E.make_points(segs))
    frames = []
    fracs = [0.25, 0.55, 0.85]
    for i, fr in enumerate(v.get("frames") or []):
        t = fr.get("t")
        if t is None:
            t = int(dur * fracs[i]) if i < len(fracs) and dur else 0
        frames.append({"url": fr.get("url", ""), "t": int(t),
                       "cap": fr.get("cap") or f"{int(t) // 60}:{int(t) % 60:02d}"})
    frames.sort(key=lambda x: x["t"])
    return {
        "id": v["id"],
        "clean_title": E.clean_title(v.get("title", "")),
        "summary": summary,
        "points": points,
        "duration_sec": dur,
        "segments": segs,
        "raw_segments": raw,
        "frames": frames,
        "has_transcript": bool(v.get("transcript")),
        "ai_refined": bool(note),
        "raw_chars": sum(len(s["text"]) for s in raw),
        "clean_chars": sum(len(s["text"]) for s in segs),
    }


def main():
    fav = json.loads(DATA.read_text(encoding="utf-8"))
    enr = json.loads(ENR.read_text(encoding="utf-8"))
    llm = {}
    if LLM_NOTES.exists():
        try:
            llm = json.loads(LLM_NOTES.read_text(encoding="utf-8"))
        except Exception:
            llm = {}

    added, refreshed = [], []
    for f in fav.get("folders", []):
        for v in f.get("videos", []):
            vid = v["id"]
            has_t = bool(v.get("transcript"))
            if vid not in enr:
                added.append(vid)
                enr[vid] = build_entry(v, llm.get(vid) or {})
            elif bool(enr[vid].get("has_transcript")) != has_t:
                refreshed.append(vid)
                enr[vid] = build_entry(v, llm.get(vid) or {})

    print(f"新增条目：{len(added)}")
    for i in added[:40]:
        print("  +", i)
    print(f"状态刷新：{len(refreshed)}")
    for i in refreshed[:20]:
        print("  ~", i)
    print(f"enriched 总数：{len(enr)}（has_transcript="
          f"{sum(1 for x in enr.values() if x.get('has_transcript'))}）")
    if DRY:
        print("（--dry，未写盘）")
        return
    ENR.write_text(json.dumps(enr, ensure_ascii=False, indent=1), encoding="utf-8")
    print("已写入 enriched.json")


if __name__ == "__main__":
    main()
