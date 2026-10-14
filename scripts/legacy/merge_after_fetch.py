# -*- coding: utf-8 -*-
"""
合并脚本（增量重抓后的安全网）
目的：
  1. 取【本次干净重抓】favorites.clean.json 作为"当前收藏"权威集合。
  2. 把【旧 favorites.json】里已有的 transcript / points / frames / no_transcript
     合并回新数据，绝不丢失已完成的 328 条转写。
  3. 剥离任何被重新抓回来的 digg / collect_count / digg_count（点赞字段）。
  4. 识别"新增视频"（本次有、旧的没有）——这些才需要重新转写。
  5. 把"仅旧数据有、本次没抓到"的视频单独存盘，避免误删丢失。

输出：
  - favorites.json            （合并后的正式数据，写入前自动再备份）
  - data/_new_videos.json     （待转写的新增视频清单）
  - data/_dropped_old.json    （仅旧数据有的视频，备查）
"""
import json
import sys
from pathlib import Path
from datetime import datetime
from shutil import copy2

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OLD = DATA / "favorites.json"
CLEAN = DATA / "favorites.clean.json"
MERGED = DATA / "favorites.json"          # 写回正式文件
NEW_LIST = DATA / "_new_videos.json"
DROPPED = DATA / "_dropped_old.json"

KEEP = ("transcript", "points", "frames", "no_transcript", "processed_at")
STRIP = ("digg", "collect_count", "digg_count")


def load(p):
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def index_old(fav):
    """遍历所有文件夹视频，按 id 建索引：保留转写相关字段"""
    idx = {}
    for f in fav.get("folders", []):
        for v in f.get("videos", []):
            vid = str(v.get("id") or "")
            if not vid:
                continue
            rec = {k: v.get(k) for k in KEEP}
            # 若同 id 多次出现，优先选有 transcript 的
            if vid not in idx or (rec.get("transcript") and not idx[vid].get("transcript")):
                idx[vid] = rec
    return idx


def main():
    old = load(OLD)
    clean = load(CLEAN)
    if old is None:
        print("!! 找不到旧 favorites.json，无法合并。中止。", flush=True)
        sys.exit(1)
    if clean is None:
        print("!! 找不到 favorites.clean.json（请先运行 fetch_favorites_clean.py）。中止。", flush=True)
        sys.exit(1)

    old_idx = index_old(old)
    old_ids = set(old_idx)

    merged_folders = []
    new_ids = []
    seen = set()
    total = 0

    for f in clean.get("folders", []):
        new_videos = []
        for v in f.get("videos", []):
            vid = str(v.get("id") or "")
            if not vid:
                continue
            # 剥离点赞字段
            for k in STRIP:
                if k in v:
                    del v[k]
            # 合并旧转写
            if vid in old_idx:
                for k in KEEP:
                    if old_idx[vid].get(k) is not None:
                        v[k] = old_idx[vid][k]
            # 初始化缺失字段
            if "transcript" not in v:
                v["transcript"] = ""
            if "points" not in v:
                v["points"] = []
            if "frames" not in v:
                v["frames"] = []
            if "no_transcript" not in v:
                v["no_transcript"] = ""
            # 统计新增
            if vid not in old_ids and vid not in seen:
                new_ids.append(vid)
            if vid not in seen:
                seen.add(vid)
                total += 1
            new_videos.append(v)
        nf = dict(f)
        nf["videos"] = new_videos
        nf["video_count"] = len(new_videos)
        merged_folders.append(nf)

    # 仅旧数据有的视频（本次没抓到）→ 单独存盘【且】并入主数据，确保零丢失
    clean_ids = seen
    dropped = []
    kept_old_only = []
    for f in old.get("folders", []):
        for v in f.get("videos", []):
            vid = str(v.get("id") or "")
            if not vid or vid in clean_ids:
                continue
            # 剥离点赞字段（双保险）
            for k in STRIP:
                if k in v:
                    del v[k]
            if "transcript" not in v:
                v["transcript"] = ""
            if "points" not in v:
                v["points"] = []
            if "frames" not in v:
                v["frames"] = []
            if "no_transcript" not in v:
                v["no_transcript"] = ""
            dropped.append({"folder": f.get("name", ""), "video": v})
            kept_old_only.append(v)

    if kept_old_only:
        merged_folders.append({
            "id": "_kept_old_only",
            "name": "_(保留-本次未抓到)",
            "total": len(kept_old_only),
            "videos": kept_old_only,
            "video_count": len(kept_old_only),
        })
        total += len(kept_old_only)

    merged = {
        "fetched_at": clean.get("fetched_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "merged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_videos": total,
        "folders": merged_folders,
    }

    # 写入前再备份一次正式文件
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bk = DATA / "_backup" / f"favorites.before_merge_{ts}.json"
    bk.parent.mkdir(parents=True, exist_ok=True)
    if MERGED.exists():
        copy2(MERGED, bk)
        print(f"已备份旧 favorites.json → {bk}", flush=True)

    MERGED.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    NEW_LIST.write_text(json.dumps(new_ids, ensure_ascii=False, indent=1), encoding="utf-8")
    DROPPED.write_text(json.dumps(dropped, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"✅ 合并完成", flush=True)
    print(f"   合并后唯一视频数: {total}", flush=True)
    print(f"   新增视频（需转写）: {len(new_ids)}", flush=True)
    print(f"   仅旧数据有（本次未抓到）: {len(dropped)} → {DROPPED.name}", flush=True)
    print(f"   已写回: {MERGED.name}", flush=True)
    print(f"   新视频清单: {NEW_LIST.name}", flush=True)
    if new_ids:
        print("   新增 id 示例:", ", ".join(new_ids[:10]), flush=True)


if __name__ == "__main__":
    main()
