# -*- coding: utf-8 -*-
"""剥离 favorites.json 中的 digg / collect_count 字段（用户要明确不要点赞数据）。
仅删除这两个字段，保留 transcript / no_transcript / points / frames 等全部其它内容。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAV = ROOT / "data" / "favorites.json"
fav = json.loads(FAV.read_text(encoding="utf-8"))
n_files = 0
for f in fav.get("folders", []):
    for v in f.get("videos", []):
        for k in ("digg", "collect_count", "digg_count"):
            if k in v:
                del v[k]
                n_files += 1
FAV.write_text(json.dumps(fav, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"✅ 已从 favorites.json 剥离点赞相关字段，共 {n_files} 处")
