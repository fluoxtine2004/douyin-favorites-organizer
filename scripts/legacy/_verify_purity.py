# -*- coding: utf-8 -*-
"""纯净度校验：新 favorites.json vs favorites.clean.json vs 旧 favorites.json（_backup）。
输出：id 一致性、剔除集合、剔除样本标题、digg 字段存在性、疑似点赞分类。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEW = ROOT / "data" / "favorites.json"
CLEAN = ROOT / "data" / "favorites.clean.json"
OLD_CANDIDATES = sorted((ROOT / "data" / "_backup").glob("favorites.before_clean*.json"), key=lambda p: p.stat().st_mtime)


def load_ids(p):
    d = json.loads(p.read_text(encoding="utf-8"))
    ids = set()
    for f in d.get("folders", []):
        for v in f.get("videos", []):
            ids.add(str(v.get("id")))
    return d, ids


new_d, new_ids = load_ids(NEW)
clean_d, clean_ids = load_ids(CLEAN)

print(f"新 favorites.json: 收藏夹 {len(new_d['folders'])} 个, 视频 {len(new_ids)} 条 (total_videos={new_d.get('total_videos')})")
print(f"clean 文件: 收藏夹 {len(clean_d['folders'])} 个, 视频 {len(clean_ids)} 条")

# (a) id 一致性
print(f"\n[a] id 一致性: 新==clean: {new_ids == clean_ids}, 差集(new-clean)={len(new_ids - clean_ids)}, 差集(clean-new)={len(clean_ids - new_ids)}")

# (b) 剔除集合 = 旧 - 新
old_p = OLD_CANDIDATES[-1] if OLD_CANDIDATES else None
removed = set()
old_d = None
if old_p:
    old_d, old_ids = load_ids(old_p)
    removed = old_ids - new_ids
    print(f"\n[b] 旧文件: {old_p.name}, 视频 {len(old_ids)} 条 → 剔除 {len(removed)} 条")

# 收藏夹名一览
print("\n新收藏夹名:", ", ".join(f['name'] for f in new_d['folders']))

# 旧文件中每个收藏夹的构成（判断被剔除的 id 是否集中在"默认收藏/点赞"夹）
if old_d:
    print("\n旧收藏夹构成（名称: 视频数）:")
    for f in old_d["folders"]:
        print(f"  {f['name']}: {len(f.get('videos', []))}")
    print("\n被剔除 id 在旧文件中的归属:")
    old_owner = {}
    for f in old_d["folders"]:
        for v in f.get("videos", []):
            old_owner[str(v["id"])] = (f["name"], v.get("title", ""))
    from collections import Counter
    c = Counter(owner for vid, (owner, _) in old_owner.items() if vid in removed)
    for owner, n in c.most_common(20):
        print(f"  {owner}: {n}")

    # 剔除样本标题（人工抽验是否像收藏内容）
    print("\n被剔除视频抽样（最多 15 条，含标题）:")
    for i, vid in enumerate(sorted(removed)):
        if i >= 15:
            break
        owner, title = old_owner.get(vid, ("?", "?"))
        print(f"  [{owner}] {title[:50]}")

# digg 字段与新数据中的点赞数字
digg_sum = sum(int(v.get("digg", 0) or 0) for f in new_d["folders"] for v in f.get("videos", []))
print(f"\n新数据 digg 字段: 存在digg字段的视频数={sum(1 for f in new_d['folders'] for v in f.get('videos',[]) if 'digg' in v)}, digg合计={digg_sum}")

# 分类/点赞字样检查
names = " ".join(f["name"] for f in new_d["folders"])
print(f"收藏夹名含'点赞': {'点赞' in names}, 含'默认': {'默认' in names}, 含'喜欢': {'喜欢' in names}")
