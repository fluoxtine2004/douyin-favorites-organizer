# -*- coding: utf-8 -*-
"""
抖音收藏抓取 v5（API 直连 + 每夹独立会话）
关键规律（2026-09-22 实测）：
  页面内 fetch 官方接口可拿到全量；但同一页面会话里调用若干次之后，
  collects/video/list 会返回空（软限流）→ 解法：**每个收藏夹用一个新加载的页面会话**，
  且视频接口是本次会话的第一个业务请求。
用法：python fetch_api2.py [--only-missing]
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
FOLDERS_FILE = ROOT / "data" / "folders.json"
FAV_URL = "https://www.douyin.com/user/self?showTab=favorite_collection"

HEAD_LIST = "/aweme/v1/web/collects/list/?device_platform=webapp&aid=6383&channel=channel_pc_web"
HEAD_VIDEOS = "/aweme/v1/web/collects/video/list/?device_platform=webapp&aid=6383&channel=channel_pc_web"
REST = ("pc_client_type=1&version_code=170400&version_name=17.4.0&cookie_enabled=true"
        "&screen_width=1380&screen_height=900&browser_language=zh-CN"
        "&browser_platform=Win32&browser_name=Chrome&browser_version=130.0.0.0")

JS = """async ([url]) => {
  try {
    const r = await fetch(url, {credentials: 'include'});
    const t = await r.text();
    try { return {ok: true, data: JSON.parse(t)}; }
    catch (e) { return {ok: false, text: t.slice(0, 120)}; }
  } catch (e) { return {ok: false, text: String(e)}; }
}"""


def log(m):
    print(m, flush=True)


def call(page, head, query):
    r = page.evaluate(JS, [f"{head}?{query}"])
    return (r.get("data") or {}) if r.get("ok") else {}


def load_folders(page):
    """拉收藏夹清单（带 total_number），缓存到 data/folders.json"""
    folders, cursor = [], 0
    while True:
        j = call(page, HEAD_LIST, f"cursor={cursor}&count=10&{REST}")
        lst = j.get("collects_list") or []
        for it in lst:
            folders.append({"id": str(it.get("collects_id") or ""),
                            "name": it.get("collects_name") or "",
                            "total": int(it.get("total_number") or 0)})
        if not j.get("has_more") or not lst:
            break
        cursor += len(lst)
        time.sleep(1.0)
    return [f for f in folders if f["id"]]


def fetch_folder(page, cid, expected):
    """在“新鲜会话”里翻页抓某个收藏夹的全部视频"""
    videos, cursor, pages = {}, 0, 0
    while pages < 15:
        j = call(page, HEAD_VIDEOS, f"collects_id={cid}&cursor={cursor}&count=10&{REST}")
        lst = j.get("aweme_list") or []
        for aw in lst:
            v = parse_aweme(aw)
            if v:
                videos[v["id"]] = v
        pages += 1
        if not lst or not j.get("has_more"):
            break
        cursor += len(lst)
        time.sleep(0.8)
    return videos


def main():
    if not acquire("fetch_api2"):
        return
    only_missing = "--only-missing" in sys.argv

    prev = {}
    if OUT_FILE.exists():
        try:
            prev = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    keep, old_by_folder, prev_folders = {}, {}, {}
    for f in prev.get("folders", []):
        prev_folders[str(f.get("id"))] = f
        old_by_folder[str(f.get("id"))] = {v["id"] for v in f.get("videos", [])}
        for v in f.get("videos", []):
            kv = {k: v[k] for k in KEEP_FIELDS if k in v}
            if kv:
                keep[v["id"]] = kv

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=False,
                                                  viewport={"width": 1380, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # 1) 收藏夹清单（缓存复用，避免频繁请求）
        folders = None
        if FOLDERS_FILE.exists():
            try:
                cached = json.loads(FOLDERS_FILE.read_text(encoding="utf-8"))
                if cached.get("saved_at", "")[:10] == time.strftime("%Y-%m-%d"):
                    folders = cached.get("folders")
                    log(f"==> 使用今日缓存的收藏夹清单（{len(folders)} 个）")
            except Exception:
                folders = None
        if not folders:
            page.goto(FAV_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            log("==> 拉取收藏夹列表…")
            folders = load_folders(page)
            FOLDERS_FILE.write_text(json.dumps(
                {"saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "folders": folders},
                ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"==> 收藏夹 {len(folders)} 个，接口标注总数 {sum(f['total'] for f in folders)} 条")

        out_folders, hit, miss = [], 0, 0
        for i, f in enumerate(folders, 1):
            old_ids = old_by_folder.get(f["id"], set())
            if only_missing and f["total"] and len(old_ids) >= f["total"]:
                log(f"[{i}/{len(folders)}] 跳过（已抓全）：{f['name']}")
                out_folders.append(prev_folders.get(f["id"]))
                continue
            # 每个夹：新加载页面 → 立即调视频接口（避开软限流）
            page.goto(FAV_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(3500)
            vids = fetch_folder(page, f["id"], f["total"])
            for vid, v in vids.items():
                if vid in keep:
                    for k, val in keep[vid].items():
                        v.setdefault(k, val)
            got = len(vids)
            flag = "✅" if (f["total"] and got >= f["total"]) else (f"⚠ 缺 {f['total'] - got}" if f["total"] else "")
            if got >= f["total"] and f["total"]:
                hit += 1
            else:
                miss += 1
            log(f"[{i}/{len(folders)}] {f['name']}：{got}/{f['total']} {flag}")
            out_folders.append({"id": f["id"], "name": f["name"], "total": f["total"],
                                "video_count": got, "videos": list(vids.values())})
            time.sleep(0.5)

        ctx.close()

    out_folders = [f for f in out_folders if f]
    total = sum(len(f.get("videos", [])) for f in out_folders)
    old_total = sum(len(f.get("videos", [])) for f in prev.get("folders", []))
    log(f"\n完成：{len(out_folders)} 个夹 / {total} 条（抓全 {hit} 个夹，未满 {miss} 个）")
    if old_total and total < old_total * 0.5:
        log(f"!! 少于已有 {old_total} 条的一半，拒绝覆盖（写 draft）")
        (ROOT / "data" / "favorites.draft.json").write_text(
            json.dumps({"total_videos": total, "folders": out_folders}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        release()
        return
    if OUT_FILE.exists():
        try:
            (ROOT / "data" / "favorites.backup.json").write_text(
                OUT_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass
    OUT_FILE.write_text(json.dumps(
        {"fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"), "total_videos": total,
         "folders": out_folders}, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"已保存到 {OUT_FILE}")
    release()


if __name__ == "__main__":
    main()
