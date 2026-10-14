# -*- coding: utf-8 -*-
"""把 recon 抓到的「全部收藏」落库：
  1) 库内已有条目 → 刷新 play_urls / cover / title / author / duration（直链有时效，必须刷新）
     已处理的字段（transcript / points / frames / no_transcript / processed_at …）一律保留
  2) 库内没有的新增条目 → 建条目并放进「默认收藏」夹（= 未归档收藏）
     图文帖（aweme_type=68 / 有 images 无 video）→ 打 no_transcript 豁免，并把图片存成 frames
  3) 把「全局收藏次序」写进 collect_order.json 的 union（build_collect_index 会据此给出精确先后）

安全：先备份 favorites.json；条数骤降则拒绝写盘。
用法：python ingest_from_probe.py [--dry]
"""
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MEDIA = ROOT / "media"
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_favorites import parse_aweme  # noqa: E402

DRY = "--dry" in sys.argv
STAMP = time.strftime("%Y%m%d-%H%M%S")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
# 重抓时必须保留的已加工字段
KEEP = ("transcript", "points", "frames", "frames_curated", "segments", "raw_segments",
        "no_transcript", "processed_at", "dl_failed_recently", "no_play_urls",
        "captured_at", "is_new")
REFRESH = ("title", "url", "cover", "play_urls", "author", "duration", "create_time")
UNFILED = "默认收藏"


def log(m):
    print(m, flush=True)


def fetch_images(aw, vid) -> list:
    """图文帖：把 images 下到 media/<id>/，返回 frames 结构（失败则空）"""
    urls = []
    for im in (aw.get("images") or []):
        cand = (im.get("url_list") or [])
        if cand:
            urls.append(cand[-1])
    if not urls:
        return []
    wd = MEDIA / vid
    wd.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, u in enumerate(urls, 1):
        dst = wd / f"img{i:02d}.jpg"
        if not (dst.exists() and dst.stat().st_size > 2000):
            try:
                req = urllib.request.Request(u, headers={"User-Agent": UA, "Referer": "https://www.douyin.com/"})
                with urllib.request.urlopen(req, timeout=25) as r:
                    dst.write_bytes(r.read())
            except Exception:
                continue
        if dst.exists() and dst.stat().st_size > 2000:
            frames.append({"url": str(dst), "t": 0, "cap": f"图{i}"})
    return frames


def main():
    probe = json.loads((DATA / "_probe_listcollection_raw.json").read_text(encoding="utf-8"))
    awemes, order = probe["awemes"], probe["order"]
    fav = json.loads((DATA / "favorites.json").read_text(encoding="utf-8"))
    prev_total = sum(len(f.get("videos", [])) for f in fav.get("folders", []))
    log(f"==> 抓取 {len(awemes)} 条 / 库内现有 {prev_total} 条记录")

    # index 现有条目
    where = {}                       # id -> (folder, video)
    for f in fav["folders"]:
        for v in f.get("videos", []):
            where.setdefault(v["id"], (f, v))

    refreshed = added = 0
    new_rows = []
    for i in order:
        aw = awemes[i]
        vid = str(aw.get("aweme_id") or "")
        if not vid:
            continue
        # 🛡 收藏护栏：collect_stat=0 表示我没收藏，绝不入库
        cs = aw.get("collect_stat")
        if cs is not None:
            try:
                if int(cs) == 0:
                    continue
            except Exception:
                pass
        parsed = parse_aweme(aw)
        if not parsed:
            continue
        is_imgpost = bool((aw.get("images") or [])) and not (aw.get("video") or {}).get("duration")
        if vid in where:
            f, v = where[vid]
            for k in REFRESH:
                if parsed.get(k) not in (None, "", []):
                    v[k] = parsed[k]
            refreshed += 1
        else:
            v = dict(parsed)
            v["captured_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            if is_imgpost:
                v["no_transcript"] = True
                fr = fetch_images(aw, vid)
                if fr:
                    v["frames"] = fr
                v["_imgpost"] = True
                log(f"    + 图文帖（无视频，已豁免转写）：{v.get('title','')[:38]}"
                    f"  图片 {len(fr)} 张")
            slot = None
            for f in fav["folders"]:
                if (f.get("name") or "") == UNFILED:
                    slot = f
                    break
            if slot is None:
                slot = {"id": UNFILED, "name": UNFILED, "total": None,
                        "video_count": 0, "videos": []}
                fav["folders"].append(slot)
            slot["videos"].append(v)
            where[vid] = (slot, v)
            added += 1
            new_rows.append({"id": vid, "title": v.get("title", ""),
                             "author": v.get("author", ""), "duration": v.get("duration", ""),
                             "order": i, "imgpost": is_imgpost})

    log(f"    刷新直链/元信息：{refreshed} 条；新增入库：{added} 条")
    for r in new_rows:
        log(f"      + [{r['order']:>4}] {r['duration']:>6}  {r['author'][:12]:<12} {r['title'][:44]}")

    total = sum(len(f.get("videos", [])) for f in fav.get("folders", []))
    fav["total_videos"] = total
    fav["fetched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    for f in fav["folders"]:
        f["video_count"] = len(f.get("videos", []))
    log(f"    落盘后总记录：{total}（原 {prev_total}）")
    if prev_total and total < prev_total * 0.9:
        log("    !! 条数骤降，拒绝覆盖")
        return 1

    if DRY:
        log("\n（--dry，未写盘）")
        return 0

    # 备份
    bk = DATA / "_backup"
    bk.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DATA / "favorites.json", bk / f"favorites.preingest-{STAMP}.json")
    (DATA / "favorites.json").write_text(json.dumps(fav, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    log(f"    备份 → favorites.preingest-{STAMP}.json")

    # 全局收藏次序 → collect_order.json.union（build_collect_index 据此给精确先后）
    co = DATA / "collect_order.json"
    obj = json.loads(co.read_text(encoding="utf-8")) if co.exists() else {}
    obj["union"] = order
    obj["union_note"] = ("全部收藏列表 listcollection 的完整次序（按收藏时间倒序，"
                         f"{len(order)} 条，{time.strftime('%Y-%m-%d %H:%M')}）")
    obj["fetched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    co.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"    collect_order.union 更新为 {len(order)} 条全局次序")

    # 首现登记（供「收藏时间」锚点推算）
    fs_path = DATA / "_first_seen.json"
    fs = json.loads(fs_path.read_text(encoding="utf-8")) if fs_path.exists() else {}
    today = time.strftime("%Y-%m-%d")
    for r in new_rows:
        fs.setdefault(r["id"], today)
    fs_path.write_text(json.dumps(fs, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "_recon_new.json").write_text(json.dumps(
        {"ingested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
         "baseline": prev_total, "captured": len(awemes),
         "refreshed": refreshed, "added": added, "new_ids": new_rows},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
