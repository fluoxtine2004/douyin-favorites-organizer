# -*- coding: utf-8 -*-
"""
生成可批注网页（列表简洁 + 详情详细 + 节点对齐 + 重要标记/回顾）
输入：data/favorites.json + data/enriched.json + config/categories.json
     + data/weekly_summary.txt + data/seen_ids.json（增量标记）+ data/marks.json（可选，网页导出的标记）
输出：dashboard.html
用法：python build_dashboard.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "templates" / "dashboard.html"
OUT = ROOT / "dashboard.html"
SEEN = ROOT / "data" / "seen_ids.json"

# 要点护栏：单条 ≤90 字、最多 3 条；超过 200 字的整段文稿判定为脏数据丢弃
POINT_HARD_MAX = 90
POINT_DROP_OVER = 200
POINT_MAX_N = 3


def clean_points(pts):
    out = []
    for p in (pts or []):
        s = " ".join(str(p).split()).strip()
        if not s or len(s) > POINT_DROP_OVER:
            continue
        if len(s) > POINT_HARD_MAX:
            s = s[:POINT_HARD_MAX].rstrip("，,、。 ") + "…"
        out.append(s)
        if len(out) >= POINT_MAX_N:
            break
    return out


def rel(p: str) -> str:
    try:
        pp = Path(p)
        return pp.relative_to(ROOT).as_posix() if str(pp).startswith(str(ROOT)) else str(p)
    except Exception:
        return str(p)


def _today() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


def _mk_ts(ct) -> int:
    """把抖音 create_time（发布时间，秒或毫秒）统一成秒级整数，失败返回 0"""
    try:
        ts = int(ct)
    except Exception:
        return 0
    if ts > 10 ** 12:      # 毫秒
        ts //= 1000
    return ts


def _mk_date(ct) -> str:
    """发布时间 → YYYY-MM-DD（无则空串）"""
    ts = _mk_ts(ct)
    if ts <= 0:
        return ""
    from datetime import datetime
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return ""


def main():
    data = json.loads((ROOT / "data" / "favorites.json").read_text(encoding="utf-8"))
    enriched = {}
    ep = ROOT / "data" / "enriched.json"
    if ep.exists():
        enriched = json.loads(ep.read_text(encoding="utf-8"))
    cfg = json.loads((ROOT / "config" / "categories.json").read_text(encoding="utf-8"))
    majors = [m for m in cfg.get("majors", []) if m != "待归类"] + ["待归类"]
    mapping = cfg.get("mapping", {})
    rules = cfg.get("rules", {})
    vmaj = {}
    vmp = ROOT / "data" / "video_major.json"
    if vmp.exists():
        try:
            vmaj = json.loads(vmp.read_text(encoding="utf-8")).get("map", {})
        except Exception:
            vmaj = {}

    def folder_major(name: str) -> str:
        if name in mapping:
            return mapping[name]
        for mj, kws in rules.items():
            if any(k.lower() in (name or "").lower() for k in kws):
                return mj
        return "待归类"
    # 人工分类修正（网页导出的 overrides.json 放到 data/ 即生效）
    ovr = {}
    op = ROOT / "data" / "overrides.json"
    if op.exists():
        try:
            _raw = json.loads(op.read_text(encoding="utf-8"))
            _raw = _raw.get("overrides", _raw) if isinstance(_raw, dict) else {}
            ovr = {k: v for k, v in _raw.items() if not str(k).startswith("_")}
        except Exception:
            ovr = {}
    # 排除名单（网页删除 / 批量清理）
    excluded = set()
    _xp = ROOT / "data" / "excluded.json"
    if _xp.exists():
        try:
            excluded = set(json.loads(_xp.read_text(encoding="utf-8")).get("ids", []))
        except Exception:
            excluded = set()
    taxo = {}
    _tp = ROOT / "data" / "taxonomy.json"
    if _tp.exists():
        try:
            taxo = {k: v for k, v in json.loads(_tp.read_text(encoding="utf-8")).items() if not k.startswith("_")}
        except Exception:
            taxo = {}
    auto_tax = {}
    _ap = ROOT / "data" / "auto_taxonomy.json"
    if _ap.exists():
        try:
            auto_tax = json.loads(_ap.read_text(encoding="utf-8")).get("map", {})
        except Exception:
            auto_tax = {}
    weekly = ""
    wp = ROOT / "data" / "weekly_summary.txt"
    if wp.exists():
        weekly = wp.read_text(encoding="utf-8").strip()

    # 每日可执行案例（agent 每周维护）
    daily_cases = {"cases": []}
    _cp = ROOT / "data" / "daily_cases.json"
    if _cp.exists():
        try:
            _raw = json.loads(_cp.read_text(encoding="utf-8"))
            daily_cases = {"cases": _raw.get("cases", []) if isinstance(_raw, dict) else []}
        except Exception:
            daily_cases = {"cases": []}

    # 收藏时间索引（由 build_collect_index.py 生成：接口顺序 + 快照首现日期）
    ci_map = {}
    _cip = ROOT / "data" / "collect_index.json"
    if _cip.exists():
        try:
            ci_map = json.loads(_cip.read_text(encoding="utf-8")).get("map", {})
        except Exception:
            ci_map = {}

    # 增量：与上次已见 id 对比
    seen = set()
    if SEEN.exists():
        try:
            seen = set(json.loads(SEEN.read_text(encoding="utf-8")))
        except Exception:
            seen = set()

    videos = []
    cur_ids = []
    for f in data.get("folders", []):
        for v in f.get("videos", []):
            vid = v["id"]
            if vid in excluded:
                continue
            cur_ids.append(vid)
            e = enriched.get(vid, {})
            _at = auto_tax.get(vid) or {}
            _o2 = ovr.get(vid) or {}
            _maj = _o2.get("major") or vmaj.get(vid) or folder_major(f.get("name", ""))
            if _o2.get("lv2"):
                _lv2, _lv3 = _o2.get("lv2"), _o2.get("lv3", "")
            elif _at.get("major") == _maj and _at.get("lv2"):
                _lv2, _lv3 = _at.get("lv2"), _at.get("lv3", "")
            else:
                # 跨类不一致或缺失 → 落到该一级下的第一个二级（保证不串类、不留空）
                _keys = list((taxo.get(_maj) or {}).keys())
                _lv2 = _keys[0] if _keys else ""
                _lv3 = ""
            _ci = ci_map.get(vid) or {}
            videos.append({
                "id": vid,
                "title": e.get("clean_title") or v.get("title", ""),
                "full_title": v.get("title", ""),
                "url": v.get("url", ""),
                "cover": v.get("cover", ""),
                "author": v.get("author", ""),
                "duration": v.get("duration", ""),
                "ts": _mk_ts(v.get("create_time")),
                "date": _mk_date(v.get("create_time")),
                # 收藏时间（我什么时候收藏的）：cb/ci 为排序键，cdate/cbefore 为展示
                "cb": _ci.get("cb", -1),
                "ci": _ci.get("ci", 10 ** 6),
                "cdate": _ci.get("date", ""),
                "cbefore": _ci.get("before", ""),
                "captured": v.get("captured_at", ""),
                "folder": (ovr.get(vid) or {}).get("folder") or f.get("name", ""),
                "major": (ovr.get(vid) or {}).get("major") or vmaj.get(vid) or folder_major(f.get("name", "")),
                "auto_major": vmaj.get(vid) or folder_major(f.get("name", "")),
                "lv2": _lv2, "lv3": _lv3,
                "tags": (ovr.get(vid) or {}).get("tags", []),
                "summary": e.get("summary", ""),
                "points": clean_points(e.get("points", [])),
                "segments": e.get("segments", []),
                "frames": [{"url": rel(fr.get("url", "")), "t": fr.get("t", 0),
                            "cap": fr.get("cap", "")} for fr in (e.get("frames") or [])],
                "has_transcript": bool(e.get("has_transcript")),
                "no_transcript": bool(v.get("no_transcript")),
            })

    new_ids = [i for i in cur_ids if i not in seen]

    # 本期新增：落盘留存（否则每次重建都会因 seen 合并而清空）
    #   fresh 非空 → 说明这是新一轮整理，覆盖；fresh 为空 → 沿用 14 天内的旧记录
    _np = ROOT / "data" / "new_ids.json"
    carried, _nd = [], ""
    if _np.exists():
        try:
            _raw = json.loads(_np.read_text(encoding="utf-8"))
            carried, _nd = list(_raw.get("ids", [])), _raw.get("date", "")
        except Exception:
            carried, _nd = [], ""
    if new_ids:
        _nd = _today()
    elif carried and _nd:
        try:
            from datetime import datetime, timedelta
            if datetime.strptime(_nd, "%Y-%m-%d") >= datetime.now() - timedelta(days=14):
                new_ids = [i for i in carried if i in set(cur_ids)]
        except Exception:
            pass
    _np.write_text(json.dumps({"date": _nd or _today(), "ids": new_ids}, ensure_ascii=False),
                   encoding="utf-8")

    folders_n = len({v["folder"] for v in videos if v["folder"]})
    html = (TPL.read_text(encoding="utf-8")
            .replace("__MAJORS__", json.dumps(majors, ensure_ascii=False))
            .replace("__DATA__", json.dumps(videos, ensure_ascii=False))
            .replace("__WEEKLY__", json.dumps({"text": weekly, "label": f"{folders_n} 个收藏夹"}, ensure_ascii=False))
            .replace("__NEW_IDS__", json.dumps(new_ids, ensure_ascii=False))
            .replace("__OVERRIDES__", json.dumps(ovr, ensure_ascii=False))
            .replace("__TAXO__", json.dumps(taxo, ensure_ascii=False))
            .replace("__DAILY_CASES__", json.dumps(daily_cases, ensure_ascii=False))
            .replace("__FOLDERS__", json.dumps(sorted({v["folder"] for v in videos if v["folder"]}), ensure_ascii=False)))
    OUT.write_text(html, encoding="utf-8")

    # 更新 seen 记录（下次运行据此判断"本期新增"）
    merged = sorted(set(seen) | set(cur_ids))
    SEEN.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")

    print(f"✅ 网页：{OUT}（{len(videos)} 条，本期新增 {len(new_ids)} 条，人工分类 {len(ovr)} 条）")


if __name__ == "__main__":
    main()
