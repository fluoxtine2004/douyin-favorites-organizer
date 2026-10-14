# -*- coding: utf-8 -*-
"""对比两个列表接口里每个 aweme 的 collect_stat，判断能否当「是否收藏」的护栏
  A) /aweme/v1/web/aweme/favorite/      （点赞）
  B) /aweme/v1/web/aweme/listcollection/（收藏）
参考：详情接口已证实 点赞视频 collect_stat=0、user_digged=1；收藏视频 collect_stat=1、user_digged=0
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "browser_profile"
URL = "https://www.douyin.com/user/self?showTab=favorite_collection"

samples = {"favorite": [], "listcollection": []}
counts = {}


def on_response(resp):
    u = resp.url
    key = None
    if "/aweme/v1/web/aweme/favorite/" in u:
        key = "favorite"
    elif "/aweme/v1/web/aweme/listcollection/" in u:
        key = "listcollection"
    if not key:
        return
    cnt = counts.setdefault(key, {"items": 0, "responses": 0})
    cnt["responses"] += 1
    try:
        j = resp.json()
    except Exception:
        return
    for a in (j.get("aweme_list") or []):
        cnt["items"] += 1
        if len(samples[key]) < 22:
            samples[key].append({
                "id": str(a.get("aweme_id")),
                "collect_stat": a.get("collect_stat"),
                "is_collects_selected": a.get("is_collects_selected"),
                "user_digged": a.get("user_digged"),
                "desc": (a.get("desc") or "")[:36],
            })


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False,
                                               viewport={"width": 1400, "height": 950},
                                               args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_timeout(7000)
    for _ in range(6):
        page.mouse.move(690, 500)
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(1400)
    ctx.close()

for k in ("favorite", "listcollection"):
    print(f"\n=== {k} ===  汇总: {counts.get(k)}")
    from collections import Counter
    print("   collect_stat 分布:", dict(Counter(str(s['collect_stat']) for s in samples[k])))
    print("   user_digged 分布:", dict(Counter(str(s['user_digged']) for s in samples[k])))
    for s in samples[k][:6]:
        print(f"   {s['id']} collect_stat={s['collect_stat']} user_digged={s['user_digged']} "
              f"selected={s['is_collects_selected']} | {s['desc']}")

(ROOT / "data" / "_probe_stat_compare.json").write_text(
    json.dumps({"samples": samples, "counts": counts}, ensure_ascii=False, indent=1), encoding="utf-8")
print("\n已存 → data/_probe_stat_compare.json")
