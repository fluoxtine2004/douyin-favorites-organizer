# -*- coding: utf-8 -*-
"""
抖音收藏抓取（API 直连版 v4）——在页面上下文里 fetch 官方接口，按 cursor 精确翻页
优势：不需要点击/滚动，按接口 has_more 翻到底，速度快（73 个夹约 2-4 分钟）且可校验完整性
用法：python fetch_api.py [--only-missing]
  --only-missing：只补抓「已抓数量 < 接口 total_number」的收藏夹
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lockutil import acquire, release  # noqa

from playwright.sync_api import sync_playwright
from fetch_favorites import parse_aweme, KEEP_FIELDS  # noqa

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "browser_profile"
OUT_FILE = ROOT / "data" / "favorites.json"

# 注意：参数顺序敏感——关键参数（collects_id/cursor/count）必须紧跟 channel_pc_web（实测过的顺序）
HEAD_LIST = "/aweme/v1/web/collects/list/?device_platform=webapp&aid=6383&channel=channel_pc_web"
HEAD_VIDEOS = "/aweme/v1/web/collects/video/list/?device_platform=webapp&aid=6383&channel=channel_pc_web"
REST = ("pc_client_type=1&version_code=170400&version_name=17.4.0&cookie_enabled=true"
        "&screen_width=1380&screen_height=900&browser_language=zh-CN"
        "&browser_platform=Win32&browser_name=Chrome&browser_version=130.0.0.0")

JS_FETCH = """async ([url]) => {
  try {
    const r = await fetch(url, {credentials: 'include'});
    const t = await r.text();
    try { return {ok: true, data: JSON.parse(t)}; }
    catch (e) { return {ok: false, text: t.slice(0, 200)}; }
  } catch (e) { return {ok: false, text: String(e)}; }
}"""


def log(m):
    print(m, flush=True)


def call(page, path, query):
    res = page.evaluate(JS_FETCH, [f"{path}?{query}"])
    if not res.get("ok"):
        log(f"  !! 接口异常 {path}: {str(res.get('text'))[:120]}")
        return None
    return res.get("data") or {}


def get_folders(page):
    """拉全部收藏夹（含 total_number）"""
    folders, cursor = [], 0
    while True:
        j = call(page, HEAD_LIST, f"&cursor={cursor}&count=10&{REST}")
        if not j:
            break
        lst = j.get("collects_list") or []
        for it in lst:
            folders.append({
                "id": str(it.get("collects_id") or it.get("collects_id_str") or ""),
                "name": it.get("collects_name") or "",
                "total": int(it.get("total_number") or 0),
            })
        if not j.get("has_more") or not lst:
            break
        cursor += len(lst)
        time.sleep(1.2)
    return folders


def get_videos(page, cid, known_ids=None, max_pages=60, expected=0):
    """拉某收藏夹全部视频；known_ids 用于增量提前停止；空结果自动退避重试（防限流）"""
    videos, cursor, pages = {}, 0, 0
    stop_at_known = 0
    empty_retry = 0
    while pages < max_pages:
        j = call(page, HEAD_VIDEOS,
                 f"&collects_id={cid}&cursor={cursor}&count=10&{REST}")
        if not j:
            break
        lst = j.get("aweme_list") or []
        # 空页但接口说还有内容 → 大概率被限流，退避后重试
        if not lst and expected and len(videos) < expected and empty_retry < 4:
            empty_retry += 1
            time.sleep(6 * empty_retry)
            continue
        for aw in lst:
            v = parse_aweme(aw)
            if not v:
                continue
            videos[v["id"]] = v
            if known_ids and v["id"] in known_ids:
                stop_at_known += 1
        pages += 1
        # 增量：一整页都是已知内容，说明后面也都是旧的，提前停
        if known_ids and lst and stop_at_known >= len(lst):
            break
        if not j.get("has_more") or not lst:
            break
        cursor += len(lst)
        time.sleep(1.0)
    return videos


def main():
    if not acquire("fetch_api"):
        return
    only_missing = "--only-missing" in sys.argv

    prev = {}
    if OUT_FILE.exists():
        try:
            prev = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
    keep, old_by_folder = {}, {}
    for f in prev.get("folders", []):
        vids = {v["id"] for v in f.get("videos", [])}
        old_by_folder[str(f.get("id"))] = vids
        for v in f.get("videos", []):
            kv = {k: v[k] for k in KEEP_FIELDS if k in v}
            if kv:
                keep[v["id"]] = kv

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=False,
                                                  viewport={"width": 1380, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.douyin.com/user/self?showTab=favorite_collection",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(4500)

        log("==> 拉取收藏夹列表…")
        folders = get_folders(page)
        log(f"==> 收藏夹 {len(folders)} 个，接口总数 {sum(f['total'] for f in folders)} 条")

        out_folders = []
        for i, f in enumerate(folders, 1):
            old_ids = old_by_folder.get(f["id"], set())
            if only_missing and len(old_ids) >= f["total"] and f["total"] > 0:
                log(f"[{i}/{len(folders)}] 跳过（已抓全 {len(old_ids)}/{f['total']}）：{f['name']}")
                continue
            log(f"[{i}/{len(folders)}] 抓取：{f['name']}（目标 {f['total']}）")
            vids = get_videos(page, f["id"], known_ids=old_ids if old_ids else None,
                              expected=f["total"])
            time.sleep(1.2)
            for vid, v in vids.items():
                if vid in keep:
                    for k, val in keep[vid].items():
                        v.setdefault(k, val)
            got = len(vids)
            flag = "✅" if got >= f["total"] else (f"⚠ 缺 {f['total'] - got}" if f["total"] else "")
            log(f"    → {got}/{f['total']} {flag}")
            out_folders.append({"id": f["id"], "name": f["name"], "total": f["total"],
                                "video_count": got, "videos": list(vids.values())})

        # 保留本次未处理的收藏夹（--only-missing 时）
        if only_missing:
            done_ids = {f["id"] for f in out_folders}
            for f in prev.get("folders", []):
                if str(f.get("id")) not in done_ids:
                    out_folders.append(f)

        ctx.close()

    total = sum(len(f.get("videos", [])) for f in out_folders)
    old_total = sum(len(f.get("videos", [])) for f in prev.get("folders", []))
    # 安全检查：新结果不足旧结果一半时拒绝覆盖（防限流/异常导致数据丢失）
    if old_total and total < old_total * 0.5:
        log(f"!! 新抓取仅 {total} 条，远少于已有 {old_total} 条 → 判定异常，拒绝覆盖（已写 data/favorites.draft.json）")
        (ROOT / "data" / "favorites.draft.json").write_text(
            json.dumps({"total_videos": total, "folders": out_folders}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        release()
        return
    # 备份旧文件
    if OUT_FILE.exists():
        try:
            (ROOT / "data" / "favorites.backup.json").write_text(
                OUT_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass
    out = {"fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "total_videos": total, "folders": out_folders}
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"\n✅ 完成：{len(out_folders)} 个收藏夹，{total} 条视频")
    log(f"已保存到 {OUT_FILE}")
    release()


if __name__ == "__main__":
    main()
