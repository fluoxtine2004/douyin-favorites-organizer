# -*- coding: utf-8 -*-
"""
数据加工：favorites.json -> data/enriched.json
  - 繁体→简体（opencc）
  - 口语清洁：去语气词/口癖、合并碎片、去重复
  - clean_title / summary / segments / raw_segments / frames(带时间戳)
  - AI 精修：若 data/llm_notes.json 存在（由 agent 逐条撰写），优先采用其中的
    summary / points / condensed（精炼后的分段），管线只做兜底

⚠ 要点必须精炼（2~3 句、单条 ≤90 字）。favorites.json 的 points 字段是整篇文稿的
  拼接（历史脏数据），**禁止**把它当要点沿用；兜底要点由 make_points(segs) 现算。
用法：python enrich.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "favorites.json"
OUT = ROOT / "data" / "enriched.json"
LLM_NOTES = ROOT / "data" / "llm_notes.json"

try:
    from opencc import OpenCC
    _cc = OpenCC("t2s")
except Exception:
    _cc = None

LEAD_FILL = re.compile(
    r"^(?:嗯+|呃+|唔+|额+|啊+|哎+|诶+|噢+|哦+|哈+|嗨+|那个|这个|就是|然后|所以说|所以|那么|其实|"
    r"对吧|是不是|你知道吧|怎么说呢|这样子|这一块|就是说|总之呢|反正|差不多|大概|基本上)+[\s，,、。]*")
END_FILL = re.compile(r"[，,、]?(?:对吧|是不是|你知道吧|怎么说呢|这样子|嗯+|呃+|啊+|呢)+[。！？]?$")
DUP = re.compile(r"(就是|然后|这个|那个|其实|所以|我们|你|我|他|它|的|了|是|在|有|和|也|都|很|就)\1+")
SENT_END = re.compile(r"[。！？!?；;]$")
KEY = re.compile(r"(关键|重点|第一|第二|第三|首先|其次|最后|建议|方法|步骤|原理|注意|结论|数据|不要|一定|核心)")


def t2s(s: str) -> str:
    return _cc.convert(s) if _cc else s


def clean_title(t: str) -> str:
    s = t2s(str(t or ""))
    s = re.sub(r"#[^\s#]+", " ", s)
    s = re.sub(r"@[^\s@]+", " ", s)
    s = re.sub(r"[\r\n]+", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" ,，。.、|｜-—")
    parts = re.split(r"[。！？!?]", s)
    first = parts[0].strip() if parts and parts[0].strip() else s
    if len(first) < 6 and len(s) > len(first):
        first = s
    s = first
    return (s[:38] + "…") if len(s) > 38 else s


def parse_duration(d) -> int:
    try:
        parts = [int(x) for x in str(d).split(":")]
    except Exception:
        return 0
    sec = 0
    for p in parts:
        sec = sec * 60 + p
    return sec


def raw_segments(transcript: str):
    segs = []
    for line in t2s(transcript or "").splitlines():
        m = re.match(r"\[(\d+):(\d+)\]\s*(.+)", line.strip())
        if not m:
            continue
        t = int(m.group(1)) * 60 + int(m.group(2))
        txt = m.group(3).strip()
        if txt:
            segs.append({"t": t, "text": txt})
    return segs


def polish_text(txt: str) -> str:
    s = txt.strip()
    for _ in range(3):
        ns = LEAD_FILL.sub("", s)
        if ns == s:
            break
        s = ns
    s = DUP.sub(r"\1", s)
    s = END_FILL.sub("", s)
    s = re.sub(r"[，,]{2,}", "，", s)
    return s.strip("，,、 ")


def polish_segments(segs, max_chars=48):
    """去口水话 + 合并碎片 + 去相邻重复"""
    out = []
    buf, buf_t = "", None
    for s in segs:
        txt = polish_text(s["text"])
        if not txt or len(txt) < 3:
            continue
        if out:
            prev = out[-1]["text"]
            # 相邻重复（whisper 常见）：包含关系且长度接近 → 跳过
            if txt in prev or (prev in txt and len(txt) - len(prev) < 12):
                continue
        if buf_t is None:
            buf_t = s["t"]
        if buf and SENT_END.search(buf):
            out.append({"t": buf_t, "text": buf})
            buf, buf_t = "", s["t"]
        buf = buf + ("，" if buf and not buf.endswith(("，", "、")) else "") + txt
        if len(buf) >= max_chars or SENT_END.search(buf):
            out.append({"t": buf_t, "text": buf.strip("，, ")})
            buf, buf_t = "", None
    if buf:
        out.append({"t": buf_t or 0, "text": buf.strip("，, ")})
    # 二次过滤：丢掉纯口水短句（无数字、无关键词、过短），保留主要内容
    kept = []
    for seg in out:
        t = seg["text"]
        if len(t) >= 8 or re.search(r"[0-9]", t) or KEY.search(t):
            kept.append(seg)
    return kept or out


def make_points(segs, max_n=3, max_len=52) -> list:
    """兜底要点：从整理后的分段里挑信息密度最高的 2~3 句，每句截短。

    ⚠ 绝不要把整段逐字稿当要点（历史 bug：favorites.json 的 points 字段其实是
       整篇文稿的拼接，早期管线直接沿用 v["points"]，导致要点变成一整篇文章）。
    """
    if not segs:
        return []
    cands = []
    for s in segs:
        txt = (s.get("text") or "").strip()
        if len(txt) < 10:
            continue
        score = (2 * len(re.findall(r"[0-9]", txt)) + 3 * len(KEY.findall(txt))
                 + (1 if 14 <= len(txt) <= 60 else 0))
        cands.append((score, s.get("t", 0), txt))
    if not cands:
        return []
    cands.sort(key=lambda x: (-x[0], x[1]))
    picked = []
    for _, _, txt in cands:
        if any(txt in p or p in txt for p in picked):
            continue
        txt = txt.strip("。！？，, ")
        if len(txt) > max_len:
            txt = txt[:max_len].rstrip("，,、 ") + "…"
        picked.append(txt)
        if len(picked) >= max_n:
            break
    return picked


POINT_HARD_MAX = 90          # 单条要点字数硬上限（护栏）
POINT_DROP_OVER = 200        # 超过此长度判定为「整篇文稿」脏数据 → 整条丢弃
POINT_MAX_N = 3              # 每条视频最多几条要点


def clean_points(points, max_n=3) -> list:
    """要点护栏：过滤掉「像一整篇文章」的条目，截断超长项，限制条数。

    任何来源（llm_notes / favorites.json 历史字段）都要过这道闸门。
    阈值见 POINT_HARD_MAX / POINT_DROP_OVER / POINT_MAX_N，与
    generate_outputs.clean_points、build_dashboard.clean_points 保持同一套规则。
    """
    out = []
    for p in (points or []):
        s = re.sub(r"\s+", " ", str(p)).strip()
        if not s or len(s) > POINT_DROP_OVER:
            continue
        if len(s) > POINT_HARD_MAX:
            s = s[:POINT_HARD_MAX].rstrip("，,、。 ") + "…"
        out.append(s)
        if len(out) >= max_n:
            break
    return out


def make_summary(segs, max_len=96) -> str:
    """兜底摘要：取信息密度最高的 1-2 句（agent 撰写 llm_notes 时会被覆盖）"""
    if not segs:
        return ""
    cands = []
    for s in segs:
        txt = s["text"]
        if len(txt) < 10:
            continue
        score = 2 * len(re.findall(r"[0-9]", txt)) + 2 * len(KEY.findall(txt)) + (1 if len(txt) >= 20 else 0)
        cands.append((score, s["t"], txt))
    if not cands:
        return ""
    cands.sort(key=lambda x: (-x[0], x[1]))
    picked, total = [], 0
    for _, t, txt in cands[:6]:
        if any(txt in p or p in txt for p in picked):
            continue
        picked.append(txt)
        total += len(txt)
        if total >= max_len or len(picked) >= 2:
            break
    out = "；".join(p.strip("。！？，, ") for p in picked)
    return (out[:max_len] + "…") if len(out) > max_len else out


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    llm = {}
    if LLM_NOTES.exists():
        try:
            llm = json.loads(LLM_NOTES.read_text(encoding="utf-8"))
        except Exception:
            llm = {}
    out = {}
    for f in data.get("folders", []):
        for v in f.get("videos", []):
            vid = v["id"]
            dur = parse_duration(v.get("duration", ""))
            raw = raw_segments(v.get("transcript", ""))
            segs = polish_segments(raw)
            note = llm.get(vid) or {}

            # AI 精修优先
            if note.get("condensed"):
                segs = [{"t": int(s.get("t", 0)), "text": t2s(s.get("text", ""))}
                        for s in note["condensed"]]
            summary = note.get("summary") or make_summary(segs)
            # ⚠ 不要用 v.get("points")：favorites.json 里该字段是整篇文稿的拼接（历史脏数据）。
            #    AI 要点优先，其次从整理后的分段里现算 2~3 句，最后统一过护栏。
            points = clean_points(note.get("points") or make_points(segs))

            frames = []
            fracs = [0.25, 0.55, 0.85]
            for i, fr in enumerate(v.get("frames") or []):
                t = fr.get("t")
                if t is None:
                    t = int(dur * fracs[i]) if i < len(fracs) and dur else 0
                frames.append({"url": fr.get("url", ""), "t": int(t),
                               "cap": fr.get("cap") or f"{int(t) // 60}:{int(t) % 60:02d}"})
            frames.sort(key=lambda x: x["t"])
            out[vid] = {
                "id": vid,
                "clean_title": clean_title(v.get("title", "")),
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
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    has_t = [r for r in out.values() if r["has_transcript"]]
    refined = sum(1 for r in has_t if r["ai_refined"])
    rw = sum(r["raw_chars"] for r in has_t)
    cw = sum(r["clean_chars"] for r in has_t)
    print(f"✅ 加工完成：{len(out)} 条（有逐字稿 {len(has_t)}，其中 AI 精修 {refined}）")
    if rw:
        print(f"   逐字稿：{rw} 字 → {cw} 字（{cw / rw * 100:.0f}%）")


if __name__ == "__main__":
    main()
