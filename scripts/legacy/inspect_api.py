# -*- coding: utf-8 -*-
"""抓一份 collects/list 原始响应，看有没有"作品数"字段 + 顺带统计各夹真实数量"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
raw = []

def on_response(resp):
    if "/aweme/v1/web/collects/list/" in resp.url:
        try:
            raw.append(resp.json())
        except Exception:
            pass

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(ROOT / "browser_profile"), headless=False,
                                               viewport={"width": 1380, "height": 900})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)
    page.goto("https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection",
              wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    for i in range(6):
        page.mouse.move(690, 500)
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(900)
    ctx.close()

print("捕获响应数:", len(raw))
if raw:
    j = raw[0]
    print("顶层键:", list(j.keys())[:10])
    # 找收藏夹条目
    def find_colls(o, out):
        if isinstance(o, dict):
            if "collects_id" in o or "collect_id" in o:
                out.append(o)
            for v in o.values():
                find_colls(v, out)
        elif isinstance(o, list):
            for v in o:
                find_colls(v, out)
        return out
    items = find_colls(j, [])
    print("收藏夹条目数:", len(items))
    if items:
        it = items[0]
        print("单条全部字段:", json.dumps(it, ensure_ascii=False)[:800])
    # 统计有 count 类字段的键名
    keys = set()
    for it in items:
        for k, v in it.items():
            if isinstance(v, int) and ("count" in k or "total" in k or "num" in k):
                keys.add(k)
    print("可能的数量字段:", keys)
