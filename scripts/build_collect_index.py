# -*- coding: utf-8 -*-
"""
把「接口收藏顺序」+「快照首现日期」合成为收藏时间索引。

背景：抖音网页接口不返回收藏时间戳，但收藏列表按【收藏时间倒序】返回，
所以「接口里的出现次序」就是真实收藏先后。能确定的部分来自：
  1) 每个收藏夹首页预览（该夹最近收藏的一批，含顺序）
  2) 「全部收藏」扁平列表 listcollection（全局最近的收藏，含顺序）
  3) 历史快照的首次入库日期（粗粒度上界）

⚠ 不要再用 /aweme/v1/web/aweme/favorite/（那是【点赞】，不是收藏）——
  2026-10-07 用户发现它曾把 20 条点赞当成「全局最近收藏」污染排序。

输出 data/collect_index.json：
{
  "generated_at": "...",
  "anchors": ["2026-09-23", "2026-10-05", "2026-10-07"],
  "coverage": {...},
  "map": {
     "<aweme_id>": {
        "cb": 2,                 # 收藏时间桶（越大越新）
        "ci": 5,                 # 桶内次序（越小越新；0 = 该夹里最近收藏）
        "date": "2026-10-07",    # 能确定的收藏日期；不能确定则 ""
        "before": "2026-09-23"   # 只能确定「早于某日」时的上界；否则 ""
     }
  }
}
用法：python build_collect_index.py
"""
import json
import glob
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORDER = ROOT / "data" / "collect_order.json"
PROBE = ROOT / "data" / "_probe_order.json"
OUT = ROOT / "data" / "collect_index.json"
BACKUP = ROOT / "data" / "_backup"
NO_RANK = 10 ** 6


def snapshot_first_seen():
    """从历史快照推出每个 id 的「首次入库日期」

    ⚠ 坑位 Q（2026-10-08 修）：只看 data/_backup/favorites.*.json 这类**备份文件**，
      而备份是「入库前」拍的 → 当天新入库的条目在备份里根本不存在，first_seen 就成了空，
      网页上那几条的「收藏日期」标签直接消失（实测 10-08 的 4 条新增全中）。
      改为再合并 data/_first_seen.json —— 它本来就是 ingest 专门为新条目登记日期的，
      取两者中**较早**的那个。
    """
    snaps = []
    for pat in (str(BACKUP / "favorites.*.json"),
                str(BACKUP / "pre_refetch_favorites*.json"),
                str(ROOT / "data" / "_dropped_old.json")):
        for p in glob.glob(pat):
            m = re.search(r"(20\d{2})(\d{2})(\d{2})", os.path.basename(p))
            if m:
                snaps.append((f"{m.group(1)}-{m.group(2)}-{m.group(3)}", p))
    snaps.sort()
    seen = {}
    for dt, p in snaps:
        try:
            d = json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for f in d.get("folders", []):
            for v in f.get("videos", []):
                vid = v.get("id")
                if vid and vid not in seen:
                    seen[vid] = dt

    # 合并显式登记表（ingest 写入），取较早者
    dates = {dt for dt, _ in snaps}
    fs_path = ROOT / "data" / "_first_seen.json"
    if fs_path.exists():
        try:
            explicit = json.loads(fs_path.read_text(encoding="utf-8"))
        except Exception:
            explicit = {}
        for vid, dt in explicit.items():
            if not isinstance(dt, str) or len(dt) < 10:
                continue
            dates.add(dt[:10])
            if vid not in seen or dt[:10] < seen[vid]:
                seen[vid] = dt[:10]
    return seen, sorted(dates)


def load_order():
    """cid -> {"name","ids"}；把 collect_order.json 与 _probe_order.json 合并（按首次出现次序）"""
    folders = {}
    union = []

    def add(cid, name, ids):
        c = folders.setdefault(cid, {"name": name or cid, "ids": [], "_seen": set()})
        if name:
            c["name"] = name
        for i in ids:
            if i not in c["_seen"]:
                c["_seen"].add(i)
                c["ids"].append(i)

    if ORDER.exists():
        d = json.loads(ORDER.read_text(encoding="utf-8"))
        for cid, info in (d.get("folders") or {}).items():
            add(cid, info.get("name"), info.get("ids") or [])
        union = list(d.get("union") or [])
    if PROBE.exists():
        d = json.loads(PROBE.read_text(encoding="utf-8"))
        meta = d.get("folder_meta") or {}
        for cid, ids in (d.get("order") or {}).items():
            if cid == "0":
                continue
            add(cid, meta.get(cid, ""), ids)
    for c in folders.values():
        c.pop("_seen", None)
    return folders, union


def main():
    folders, union = load_order()
    seen, anchors = snapshot_first_seen()
    date2cb = {d: i for i, d in enumerate(anchors)}
    earliest = anchors[0] if anchors else ""

    # 夹名 -> 该夹实际抓到的顺序条数（用于给「没抓到名次」的同夹视频一个合理的兜底名次）
    name_cap = {}
    name_rank = {}      # (name, vid) -> rank
    rank = {}           # vid -> 最小名次
    for cid, info in folders.items():
        nm = info["name"]
        ids = info["ids"]
        name_cap[nm] = max(name_cap.get(nm, 0), len(ids))
        for i, vid in enumerate(ids):
            name_rank[(nm, vid)] = min(name_rank.get((nm, vid), NO_RANK), i)
            if vid not in rank or i < rank[vid]:
                rank[vid] = i
    # 全部收藏扁平列表（listcollection）：其中的次序就是「全局收藏倒序」，
    # 整体压过其它一切，并按其内部顺序排列 → 单独给一个最高桶
    TOP_CB = len(anchors)
    union_pos = {vid: j for j, vid in enumerate(union) if vid}

    fav = json.loads((ROOT / "data" / "favorites.json").read_text(encoding="utf-8"))
    mp = {}
    seen_ids = set()
    exact_union = exact_rank = fallback = 0
    for f in fav.get("folders", []):
        nm = f.get("name", "")
        for v in f.get("videos", []):
            vid = v["id"]
            if vid in seen_ids:          # 同一视频可能在两个夹里，只按唯一视频计一次
                continue
            seen_ids.add(vid)
            fs = seen.get(vid, "")
            if vid in union_pos:
                cb, ci = TOP_CB, union_pos[vid]
                date, before = (fs or ""), ""
                exact_union += 1
                mp[vid] = {"cb": cb, "ci": ci, "date": date, "before": before}
                continue
            if fs == earliest:
                cb, date, before = date2cb.get(fs, 0), "", earliest
            else:
                cb, date, before = date2cb.get(fs, len(anchors)), (fs or ""), ""
            ci = rank.get(vid)
            if ci is None:
                # 该夹没抓到这条 → 名次放到「已抓到窗口」之后
                ci = name_cap.get(nm, NO_RANK)
                if ci < NO_RANK:
                    fallback += 1
                else:
                    ci = NO_RANK
            else:
                exact_rank += 1
            mp[vid] = {"cb": cb, "ci": ci, "date": date, "before": before}
    exact = exact_union + exact_rank

    OUT.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "anchors": anchors,
        "note": "cb 越大越新；ci 越小越新（0=该夹最近收藏）；date 为可确定的收藏日期",
        "coverage": {"total": len(mp), "exact_order": exact, "folder_fallback": fallback},
        "map": mp,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"锚点日期: {anchors}")
    print(f"索引条目: {len(mp)}")
    print(f"  有确切收藏次序: {exact}（全部收藏列表 {exact_union} + 夹内名次 {exact_rank}）")
    print(f"  退到「夹窗口之后」: {fallback}")
    print(f"  无任何次序: {len(mp) - exact - fallback}")
    print(f"  有确切收藏日期: {sum(1 for x in mp.values() if x['date'])}")
    print(f"  只能定位到「早于 {earliest}」: {sum(1 for x in mp.values() if x['before'])}")
    print(f"全部收藏(listcollection): {len(union)} 条")
    print(f"已写 → {OUT}")


if __name__ == "__main__":
    main()
