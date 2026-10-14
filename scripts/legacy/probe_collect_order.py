# -*- coding: utf-8 -*-
"""抓取收藏列表的【原始顺序】（不动 favorites.json），用于验证接口是否按收藏时间倒序。
输出 data/_probe_order.json = {"favorite": [id...], "folders": {cid: [id...]}, "folder_meta": {...}}
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "browser_profile"
FAV_URL = "https://www.douyin.com/user/self?showTab=favorite_collection"
LIST_URL = "https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection"

order = {"0": []}          # cid -> [id...] 按响应顺序
seen = {"0": set()}
folder_meta = {}           # cid -> name
SCROLL_ROUNDS = int(__import__("sys").argv[1]) if len(__import__("sys").argv) > 1 else 25


def find_dicts(obj, key):
    out = []
    if isinstance(obj, dict):
        if key in obj:
            out.append(obj)
        for v in obj.values():
            out.extend(find_dicts(v, key))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(find_dicts(v, key))
    return out


def on_response(resp):
    u = resp.url
    try:
        if "/aweme/v1/web/collects/list/" in u:
            j = resp.json()
            for d in find_dicts(j, "collect_id") + find_dicts(j, "collects_id"):
                cid = str(d.get("collect_id") or d.get("collects_id") or "")
                if cid:
                    folder_meta[cid] = d.get("name") or d.get("collects_name") or ""
        elif "/aweme/v1/web/collects/video/list/" in u:
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(u).query)
            cid = str((q.get("collects_id") or q.get("collect_id") or [""])[0]) or "0"
            _absorb(resp.json(), cid)
        elif "/aweme/v1/web/aweme/favorite/" in u:
            _absorb(resp.json(), "0")
    except Exception:
        pass


def _absorb(j, cid):
    order.setdefault(cid, [])
    seen.setdefault(cid, set())
    for a in (j.get("aweme_list") or []):
        vid = str(a.get("aweme_id") or "")
        if vid and vid not in seen[cid]:
            seen[cid].add(vid)
            order[cid].append(vid)


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        str(PROFILE_DIR), headless=False, viewport={"width": 1380, "height": 900},
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)


    def wheel(n=1, dy=3000, pause=1.4):
        for _ in range(n):
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            try:
                page.mouse.move(690, 500)
                page.mouse.wheel(0, dy)
            except Exception:
                pass
            page.wait_for_timeout(int(pause * 1000))


    print("==> 1/2 全部收藏（默认收藏来源）…")
    page.goto(FAV_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(3500)
    try:
        t = page.get_by_text("视频", exact=True).first
        if t.count() > 0 and t.is_visible():
            t.click()
            page.wait_for_timeout(2500)
            print("    已点「视频」子标签")
    except Exception as e:
        print("    视频标签:", str(e)[:60])
    last, idle = -1, 0
    for i in range(40):
        wheel(1, 3000, 1.4)
        n = len(order["0"])
        print(f"    轮 {i+1}: 全部收藏 {n} 条", flush=True)
        if n == last:
            idle += 1
            if idle >= 3:
                break
        else:
            idle, last = 0, n
    print(f"    全部收藏顺序条数 = {len(order['0'])}")

    print("\n==> 2/2 各收藏夹（按夹内顺序）…")
    page.goto(LIST_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    try:
        t = page.get_by_text("收藏夹", exact=True).first
        if t.count() > 0 and t.is_visible():
            t.click()
            page.wait_for_timeout(2500)
    except Exception:
        pass

    names = [v for v in folder_meta.values() if v]
    print("    已知收藏夹:", len(names))
    for nm in names:
        try:
            loc = page.get_by_text(nm, exact=True)
            if loc.count() == 0:
                loc = page.get_by_text(nm, exact=False)
            if loc.count() == 0:
                continue
            loc.nth(0).click(timeout=4000)
            page.wait_for_timeout(3000)
            before = sum(len(v) for c, v in order.items() if c != "0")
            last, idle = -1, 0
            for _ in range(20):
                wheel(1, 3000, 1.2)
                cur = sum(len(v) for c, v in order.items() if c != "0")
                if cur == last:
                    idle += 1
                    if idle >= 3:
                        break
                else:
                    idle, last = 0, cur
            after = sum(len(v) for c, v in order.items() if c != "0")
            print(f"    {nm}: +{after - before} 条（累计 {after}）", flush=True)
        except Exception as e:
            print(f"    {nm}: 跳过（{str(e)[:36]}）")
        try:
            page.goto(LIST_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            tt = page.get_by_text("收藏夹", exact=True).first
            if tt.count() > 0 and tt.is_visible():
                tt.click()
                page.wait_for_timeout(2000)
        except Exception:
            pass

    out = {"order": order, "folder_meta": folder_meta}
    (ROOT / "data" / "_probe_order.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n全部收藏顺序条数:", len(order["0"]))
    print("收藏夹数:", len([c for c in order if c != "0"]))
    print("已存 → data/_probe_order.json")
    ctx.close()
