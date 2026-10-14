# -*- coding: utf-8 -*-
"""一次性清洗：剔除混入的【点赞】视频 + 把「整篇文稿当要点」改回精炼要点。

背景（2026-10-07 用户第二次发现，属回归）：
  1) fetch_gap.py 曾监听 /aweme/v1/web/aweme/favorite/（那是【点赞/喜欢】列表！）
     并把结果灌进 cid="0"，再被命名为「默认收藏」→ 36 条点赞混进知识库。
     证据：这 36 条 collect_stat=0 / user_digged=1；73 个真收藏夹里没有「默认收藏」；
           listcollection（真·全部收藏）里这 36 条一条都不在。
  2) favorites.json 的 points 字段其实是【整篇逐字稿的拼接】，早期管线直接沿用，
     导致网页/Obsidian 的「AI 要点」变成一整篇文章。用户截图投诉过。

本脚本做四件事（全部幂等、先备份）：
  A. favorites.json：删掉「默认收藏」夹；把 points 换成精炼要点（llm_notes 优先，
     否则用整理后的分段现算 2~3 句），统一过字数护栏。
  B. enriched.json / seen_ids.json / new_ids.json / _first_seen.json：清掉这些 id。
  C. collect_order.json：清掉点赞来源的 union（下次由 fetch_collect_order.py 重采真·收藏）。
  D. 删除 vault 里对应 36 条的 Obsidian 笔记。

用法：python clean_digg_contamination.py [--dry]
"""
import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "scripts"))
import enrich as E  # noqa: E402

DRY = "--dry" in sys.argv
BAD_FOLDER = "默认收藏"
STAMP = time.strftime("%Y%m%d-%H%M%S")
BACKUP = DATA / "_backup"
report = []


def log(m):
    print(m, flush=True)


def backup(p: Path):
    if not p.exists():
        return
    BACKUP.mkdir(parents=True, exist_ok=True)
    dst = BACKUP / f"{p.stem}.predigg-{STAMP}{p.suffix}"
    shutil.copy2(p, dst)
    log(f"  备份 → {dst.name}")


def load(p, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def dump(p: Path, obj):
    if DRY:
        return
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    log("=== 清洗：点赞混入 + 要点消肿 ===")
    fav = load(DATA / "favorites.json")
    if fav is None:
        log("!! 读不到 favorites.json，终止")
        return 1

    # ---------- 定位「默认收藏」 ----------
    digg_ids, digg_titles = [], []
    kept_folders = []
    for f in fav.get("folders", []):
        if (f.get("name") or "") == BAD_FOLDER:
            for v in f.get("videos", []):
                digg_ids.append(v["id"])
                digg_titles.append(v.get("title", ""))
        else:
            kept_folders.append(f)

    log(f"\n[A] 疑似点赞混入「{BAD_FOLDER}」：{len(digg_ids)} 条（整夹删除）")
    for t in digg_titles[:6]:
        log(f"      - {t[:50]}")
    if len(digg_titles) > 6:
        log(f"      … 共 {len(digg_titles)} 条")

    # 修 1：删掉「默认收藏」夹
    fav["folders"] = kept_folders

    # ---------- 要点消肿 ----------
    llm = load(DATA / "llm_notes.json", {}) or {}
    digest = 0
    still_long = 0
    newpts = {}                       # vid -> 精炼后的要点
    renamed = 0
    for f in fav["folders"]:
        for v in f.get("videos", []):
            note = llm.get(v["id"]) if isinstance(llm.get(v["id"]), dict) else {}
            raw = E.raw_segments(v.get("transcript", ""))
            segs = E.polish_segments(raw)
            if (note or {}).get("condensed"):
                segs = [{"t": int(s.get("t", 0)), "text": E.t2s(s.get("text", ""))}
                        for s in note["condensed"]]
            pts = E.clean_points((note or {}).get("points") or E.make_points(segs))
            old = v.get("points") or []
            if sum(len(str(p)) for p in old) > E.POINT_HARD_MAX:
                digest += 1
            if any(len(str(p)) > E.POINT_HARD_MAX for p in pts):
                still_long += 1
            v["points"] = pts
            newpts[v["id"]] = pts
            renamed += 1

    fav["total_videos"] = sum(len(f.get("videos", [])) for f in fav["folders"])
    log(f"\n[B] 要点消肿：处理 {renamed} 条，其中 {digest} 条原来是「整篇文稿」→ 已改成 2~3 句")
    log(f"     仍超 {E.POINT_HARD_MAX} 字的：{still_long}（应为 0）")
    log(f"     清洗后总条数：{fav['total_videos']}")

    # ---------- 落盘 ----------
    if DRY:
        log("\n（--dry，未写盘）")
        return 0

    log("\n[C] 备份 + 写盘")
    for name in ("favorites.json", "enriched.json", "seen_ids.json",
                 "new_ids.json", "collect_order.json", "_first_seen.json"):
        backup(DATA / name)

    dump(DATA / "favorites.json", fav)

    # ---------- 清 enriched / seen / new ----------
    bad = set(digg_ids)
    enr = load(DATA / "enriched.json", {}) or {}
    n_enr = len(bad & set(enr))
    for i in bad:
        enr.pop(i, None)
    # enriched 的 points 同步消肿（其余字段一概不动，保护已精修的 summary/segments）
    n_fix = 0
    for vid, pts in newpts.items():
        if vid in enr and enr[vid].get("points") != pts:
            enr[vid]["points"] = pts
            n_fix += 1
    dump(DATA / "enriched.json", enr)
    log(f"  enriched.json：-{n_enr} 条 → {len(enr)}；要点同步消肿 {n_fix} 条")
    miss = [i for i in newpts if i not in enr]
    if miss:
        log(f"  ⚠ favorites 有但 enriched 缺 {len(miss)} 条：{miss[:5]}…（可跑 refill_enriched.py 补齐）")
    # 孤儿条目：enriched 有、favorites 已无（历史遗留，任何界面都不会显示）→ 清掉
    orphan = [k for k in enr if k not in newpts]
    for k in orphan:
        enr.pop(k, None)
    if orphan:
        dump(DATA / "enriched.json", enr)
        log(f"  清理孤儿条目 {len(orphan)} 条：{orphan[:5]} → enriched 现 {len(enr)} 条")

    seen = load(DATA / "seen_ids.json", []) or []
    seen2 = [i for i in seen if i not in bad]
    dump(DATA / "seen_ids.json", seen2)
    log(f"  seen_ids.json：{len(seen)} → {len(seen2)}（-{len(seen) - len(seen2)}）")

    nj = load(DATA / "new_ids.json", {}) or {}
    old_ids = list(nj.get("ids", []))
    nj["ids"] = [i for i in old_ids if i not in bad]
    dump(DATA / "new_ids.json", nj)
    log(f"  new_ids.json：{len(old_ids)} → {len(nj['ids'])}")

    fs = load(DATA / "_first_seen.json", {}) or {}
    n_fs = len(bad & set(fs))
    for i in bad:
        fs.pop(i, None)
    dump(DATA / "_first_seen.json", fs)
    log(f"  _first_seen.json：-{n_fs} 条")

    # ---------- 清 collect_order 的点赞 union ----------
    co = load(DATA / "collect_order.json", {}) or {}
    old_union = list(co.get("union", []))
    co["union"] = [i for i in old_union if i not in bad]
    co["_note"] = "union 已剔除点赞来源；下次运行 fetch_collect_order.py 会重采真·收藏"
    dump(DATA / "collect_order.json", co)
    log(f"  collect_order.json union：{len(old_union)} → {len(co['union'])}")

    # ---------- 删 vault 笔记 ----------
    # ⚠ 只删「原链接」恰好指向被剔除视频的【视频笔记】；
    #   绝不按「文中提到该链接」删——专题笔记会引用多条视频，会被误删。
    removed, skipped = [], 0
    want_lines = {f"原链接: https://www.douyin.com/video/{i}" for i in bad}
    for md in (ROOT / "vault").rglob("*.md"):
        if md.parent.name in ("专题", "00-周报"):
            continue
        try:
            txt = md.read_text(encoding="utf-8")
        except Exception:
            continue
        if any(ln.strip() in want_lines for ln in txt.splitlines()):
            md.unlink()
            removed.append(md.name)
        elif any(f"/video/{i}" in txt for i in bad):
            skipped += 1          # 只是引用，不删
    log(f"\n[D] 删除被剔除视频的笔记 {len(removed)} 篇（跳过仅引用的 {skipped} 篇）")
    for n in removed[:6]:
        log(f"      - {n[:60]}")

    log("\n✅ 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
