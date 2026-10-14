# -*- coding: utf-8 -*-
"""把发布时间(create_time)早于 2025-01-01 的条目并入 excluded.json。

- 口径：create_time 发布年份 < 2025（与既有 `exclude_all_pre2024` 同一口径）
- 「删除」= 进排除名单（网页/Obsidian/周报不再出现，重抓跳过），不动 media/vault 文件
- 只读预演：`python -B scripts/exclude_pre2025.py --dry`
"""
import json, sys, shutil, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CUTOFF_YEAR = 2025

DRY = "--dry" in sys.argv


def yr(ts):
    ts = int(ts)
    ts = ts // 1000 if ts > 1e12 else ts
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).year


def main():
    fav = json.loads((DATA / "favorites.json").read_text(encoding="utf-8"))
    ex = json.loads((DATA / "excluded.json").read_text(encoding="utf-8"))
    ex_ids = [str(x) for x in ex.get("ids", [])]
    ex_set = set(ex_ids)

    uniq = {}
    for f in fav["folders"]:
        for v in f.get("videos", []):
            uniq.setdefault(str(v["id"]), (f["name"], v))

    targets = {  # id -> (year, folder, title)
        i: (yr(v["create_time"]), fold, str(v.get("title") or ""))
        for i, (fold, v) in uniq.items()
        if yr(v["create_time"]) < CUTOFF_YEAR
    }
    to_add = sorted(i for i in targets if i not in ex_set)

    print(f"唯一视频 {len(uniq)}")
    print(f"pre-{CUTOFF_YEAR} 唯一视频 {len(targets)}")
    print(f"已排除 {len(ex_set)}，其中 pre-{CUTOFF_YEAR} 已排除 {len(targets) - len(to_add)}")
    print(f"本次需新增排除 {len(to_add)}")

    if DRY:
        print("\n[dry] 预览前 20 条，未写盘：")
        for i in to_add[:20]:
            y, fold, title = targets[i]
            print(f"  {y} [{fold}] {title[:56]}")
        return

    if not to_add:
        print("无需新增，退出。")
        return

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    # 1) 备份 excluded.json
    bdir = DATA / "_backup"
    bdir.mkdir(exist_ok=True)
    shutil.copy2(DATA / "excluded.json", bdir / f"excluded.pre2025_{ts}.json")
    # 2) 快照（可回滚）
    snap = DATA / f"removed_pre2025_{ts}.json"
    snap.write_text(json.dumps({
        "ts": ts, "criteria": f"create_time < {CUTOFF_YEAR}-01-01", "added": len(to_add),
        "items": [{"id": i, "y": targets[i][0], "folders": [targets[i][1]], "title": targets[i][2]} for i in to_add],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    # 3) 合并
    ex["ids"] = ex_ids + to_add
    ex.setdefault("history", []).append({
        "ts": datetime.datetime.now().isoformat(),
        "action": f"exclude_all_pre{CUTOFF_YEAR}",
        "added": len(to_add),
        "criteria": f"create_time < {CUTOFF_YEAR}-01-01",
        "snapshot": f"data/{snap.name}",
    })
    ex["_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tmp = DATA / "excluded.json.tmp"
    tmp.write_text(json.dumps(ex, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(DATA / "excluded.json")

    print(f"\n✅ 已写入 excluded.json：{len(ex_ids)} → {len(ex['ids'])}（+{len(to_add)}）")
    print(f"   备份 {bdir / f'excluded.pre2025_{ts}.json'}")
    print(f"   快照 {snap}")


if __name__ == "__main__":
    main()
