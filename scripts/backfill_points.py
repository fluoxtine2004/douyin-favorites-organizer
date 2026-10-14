# -*- coding: utf-8 -*-
"""
回填要点：给「有逐字稿但 points 为空」的条目重算要点（2026-10-10 建立）

为什么需要：批量转写过程中，早期进程用的是修复前的 `summarize_points`
（坑位 U：whisper 逐字稿零标点时要点恒为空），这些条目已写进 favorites.json 但 points=[]。
本脚本用当前（已修复）的切分逻辑重算并回填，**只动 points 字段**，其余不碰。

用法：
  python scripts/backfill_points.py --dry    # 只看会改多少条
  python scripts/backfill_points.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from batch_transcribe import summarize_points  # noqa
from enrich import clean_points  # noqa

DATA_FILE = ROOT / "data" / "favorites.json"


def main():
    dry = "--dry" in sys.argv
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    fixed = 0
    bad = 0
    for f in data.get("folders", []):
        for v in f.get("videos", []):
            tr = v.get("transcript")
            if not tr:
                continue
            pts = clean_points(v.get("points") or [], max_n=3)
            if pts:
                if pts != (v.get("points") or []):
                    if not dry:
                        v["points"] = pts
                continue
            # points 为空 → 重算
            new_pts = summarize_points(tr, v.get("title", ""))
            if new_pts:
                if not dry:
                    v["points"] = new_pts
                fixed += 1
            else:
                bad += 1
    print(f"待回填 {fixed} 条 / 仍算不出 {bad} 条" + ("（dry run）" if dry else ""))
    if not dry and fixed:
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print("已写回 favorites.json")


if __name__ == "__main__":
    main()
