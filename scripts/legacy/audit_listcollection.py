# -*- coding: utf-8 -*-
"""验证 /aweme/v1/web/aweme/listcollection/ 是真实收藏列表，并算出「未归档收藏」"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "browser_profile"
URL = "https://www.douyin.com/user/self?showTab=favorite_collection"

ids = []
seen = set()
totals = []


def on_response(resp):
    if "/aweme/v1/web/aweme/listcollection/" in resp.url:
        try:
            j = resp.json()
        except Exception:
            return
        totals.append({k: j.get(k) for k in ("status_code", "cursor", "has_more", "total_number")})
        for a in (j.get("aweme_list") or []):
            v = str(a.get("aweme_id") or "")
            if v and v not in seen:
                seen.add(v)
                ids.append(v)
    elif "/aweme/v1/web/aweme/favorite/" in resp.url:
        try:
            fav_count = len(resp.json().get("aweme_list") or [])
        except Exception:
            fav_count = -1
        totals.append({"#favorite(点赞)返回": fav_count})


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False,
                                               viewport={"width": 1400, "height": 950},
                                               args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    last, idle = -1, 0
    for i in range(80):
        page.mouse.move(690, 500)
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(1400)
        n = len(ids)
        if i % 5 == 0 or n != last:
            print(f"  轮 {i+1}: {n} 条", flush=True)
        if n == last:
            idle += 1
            if idle >= 4:
                break
        else:
            idle = 0
        last = n
    ctx.close()

print(f"\nlistcollection 累计 {len(ids)} 条")
print("响应样本:", totals[:3], "...", totals[-2:])

fav = json.loads((ROOT / "data" / "favorites.json").read_text(encoding="utf-8"))
filed, loose_old = set(), set()
for f in fav.get("folders", []):
    nm = f.get("name") or ""
    for v in f.get("videos", []):
        (loose_old if nm == "默认收藏" else filed).add(v["id"])

lc = set(ids)
print(f"\n命名收藏夹已有 {len(filed)} 条")
print(f"采集到的 listcollection {len(lc)} 条")
print(f"  listcollection ∩ 命名夹 = {len(lc & filed)}")
print(f"  listcollection 独有（= 未归档收藏）= {len(lc - filed)}")
print(f"  命名夹有但 listcollection 没返回 = {len(filed - lc)}")
print(f"\n旧「默认收藏」{len(loose_old)} 条中，真正属于收藏的 = {len(loose_old & lc)}")
print(f"旧「默认收藏」里不在收藏列表（即点赞混入）= {len(loose_old - lc)}")

(ROOT / "data" / "_probe_listcollection.json").write_text(
    json.dumps({"ids": ids, "responses": totals}, ensure_ascii=False, indent=1), encoding="utf-8")
print("已存 → data/_probe_listcollection.json")
