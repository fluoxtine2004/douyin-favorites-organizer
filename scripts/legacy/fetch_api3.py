# -*- coding: utf-8 -*-
"""
抖音收藏抓取 v6（最稳组合）
  A. 收藏夹清单+总数：监听页面自身 XHR（进入收藏夹子标签并滚动）
  B. 逐夹内容：每个夹新开一次页面 → 立即调 collects/video/list 翻页（避开软限流）
用法：python fetch_api3.py [--only-missing]
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from lockutil import acquire, release  # noqa
from playwright.sync_api import sync_playwright
from fetch_favorites import parse_aweme, KEEP_FIELDS  # noqa

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "browser_profile"
OUT = ROOT / "data" / "favorites.json"
FOLDERS_CACHE = ROOT / "data" / "folders.json"
FAV = "https://www.douyin.com/user/self?showTab=favorite_collection"
LIST_URL = "https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection"
HEAD = "/aweme/v1/web/collects/video/list/?device_platform=webapp&aid=6383&channel=channel_pc_web"
REST = ("pc_client_type=1&version_code=170400&version_name=17.4.0&cookie_enabled=true"
        "&screen_width=1380&screen_height=900&browser_language=zh-CN"
        "&browser_platform=Win32&browser_name=Chrome&browser_version=130.0.0.0")
JS = """async ([url]) => {
  try { const r = await fetch(url, {credentials:'include'}); const t = await r.text();
        try { return {ok:true, data:JSON.parse(t)}; } catch(e){ return {ok:false}; } }
  catch(e) { return {ok:false}; }
}"""

def log(m): print(m, flush=True)

def collect_folders(page):
    """监听页面自身 XHR 拿收藏夹清单+总数"""
    found = {}
    def on_resp(resp):
        if "/aweme/v1/web/collects/list/" in resp.url:
            try: j = resp.json()
            except Exception: return
            for it in j.get("collects_list") or []:
                cid = str(it.get("collects_id") or "")
                if cid:
                    found[cid] = {"id": cid, "name": it.get("collects_name") or "",
                                  "total": int(it.get("total_number") or 0)}
    page.on("response", on_resp)
    page.goto(LIST_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(4500)
    try:
        tab = page.get_by_text("收藏夹", exact=True).first
        if tab.count() > 0 and tab.is_visible():
            tab.click(); page.wait_for_timeout(2500)
    except Exception: pass
    for _ in range(30):
        page.mouse.move(690, 500)
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(700)
    return list(found.values())

def fetch_folder(page, cid):
    videos, cursor, pages = {}, 0, 0
    while pages < 15:
        r = page.evaluate(JS, [f"{HEAD}?collects_id={cid}&cursor={cursor}&count=10&{REST}"])
        j = r.get("data") or {}
        lst = j.get("aweme_list") or []
        for aw in lst:
            v = parse_aweme(aw)
            if v: videos[v["id"]] = v
        pages += 1
        if not lst or not j.get("has_more"): break
        cursor += len(lst)
        time.sleep(0.7)
    return videos

def main():
    if not acquire("fetch_api3"): return
    only_missing = "--only-missing" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    prev, keep, prev_folders, old_ids = {}, {}, {}, {}
    if OUT.exists():
        try: prev = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception: prev = {}
    for f in prev.get("folders", []):
        prev_folders[str(f.get("id"))] = f
        old_ids[str(f.get("id"))] = {v["id"] for v in f.get("videos", [])}
        for v in f.get("videos", []):
            kv = {k: v[k] for k in KEEP_FIELDS if k in v}
            if kv: keep[v["id"]] = kv

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=False,
                                                  viewport={"width":1380,"height":900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        folders = None
        if FOLDERS_CACHE.exists():
            try:
                c = json.loads(FOLDERS_CACHE.read_text(encoding="utf-8"))
                if c.get("saved_at","")[:10] == time.strftime("%Y-%m-%d") and c.get("folders"):
                    folders = c["folders"]; log(f"==> 用今日缓存清单（{len(folders)} 夹）")
            except Exception: folders = None
        if not folders:
            log("==> 监听页面请求，收集收藏夹清单…")
            folders = collect_folders(page)
            FOLDERS_CACHE.write_text(json.dumps({"saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                                "folders": folders}, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"==> 收藏夹 {len(folders)} 个 / 标注总数 {sum(f['total'] for f in folders)} 条")

        out, hit = [], 0
        if limit: folders = folders[:limit]
        for i, f in enumerate(folders, 1):
            if only_missing and f["total"] and len(old_ids.get(f["id"], ())) >= f["total"]:
                log(f"[{i}/{len(folders)}] 跳过（已全）：{f['name']}")
                if prev_folders.get(f["id"]): out.append(prev_folders[f["id"]])
                continue
            # 每个收藏夹开一个全新浏览器会话（软限流按会话计算）
            try:
                ctx.close()
            except Exception:
                pass
            ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=False,
                                                       viewport={"width": 1380, "height": 900})
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(FAV, wait_until="domcontentloaded")
            page.wait_for_timeout(3200)
            vids = fetch_folder(page, f["id"])
            for vid, v in vids.items():
                if vid in keep:
                    for k, val in keep[vid].items(): v.setdefault(k, val)
            got = len(vids)
            ok = f["total"] and got >= f["total"]
            if ok: hit += 1
            log(f"[{i}/{len(folders)}] {f['name']}：{got}/{f['total']} {'✅' if ok else ('⚠ 缺 %d' % (f['total']-got) if f['total'] else '')}")
            out.append({"id": f["id"], "name": f["name"], "total": f["total"],
                        "video_count": got, "videos": list(vids.values())})
            time.sleep(0.4)
        ctx.close()

    total = sum(len(f.get("videos", [])) for f in out)
    old_total = sum(len(f.get("videos", [])) for f in prev.get("folders", []))
    log(f"\n完成：{len(out)} 夹 / {total} 条（抓全 {hit} 个夹）")
    if old_total and total < old_total * 0.5:
        log(f"!! 结果异常（{total} < {old_total}/2），拒绝覆盖")
        (ROOT/"data"/"favorites.draft.json").write_text(json.dumps({"total_videos": total, "folders": out}, ensure_ascii=False, indent=1), encoding="utf-8")
        release(); return
    if OUT.exists():
        try: (ROOT/"data"/"favorites.backup.json").write_text(OUT.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception: pass
    OUT.write_text(json.dumps({"fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                               "total_videos": total, "folders": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"已保存到 {OUT}")
    release()

if __name__ == "__main__":
    main()
