# -*- coding: utf-8 -*-
"""判定 aweme/favorite 是【收藏】还是【点赞】：
  ① 取 collects/list 每个收藏夹的 total_number，求和 = 已归档收藏数
  ② 读「收藏夹」页面上显示的收藏总数（收集和点赞页各自的计数）
  ③ 若 ① 与页面收藏总数吻合 → 没有额外「未归档收藏」→ 默认收藏(来自 aweme/favorite) 是点赞
     若 页面收藏总数 > ① → 差额就是未归档收藏，再与默认收藏条数比对
"""
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "browser_profile"
LIST_URL = "https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection"
FAV_URL = "https://www.douyin.com/user/self?showTab=favorite_collection"
COLLECT_URL = "https://www.douyin.com/user/self?showTab=collection"      # 可能不存在，仅试探

folders = {}          # cid -> {name,total}
counter = {"favorite": 0, "video_list": 0}
probe = {"favorite_tops": [], "list_tops": []}


def on_response(resp):
    u = resp.url
    try:
        if "/aweme/v1/web/collects/list/" in u:
            j = resp.json()
            probe["list_tops"].append({k: j.get(k) for k in
                                       ("status_code", "total_number", "has_more", "cursor")})
            for it in (j.get("collects_list") or []):
                cid = str(it.get("collects_id") or "")
                if cid:
                    folders[cid] = {"name": it.get("collects_name") or "",
                                    "total": int(it.get("total_number") or 0)}
        elif "/aweme/v1/web/collects/video/list/" in u:
            counter["video_list"] += len(resp.json().get("aweme_list") or [])
        elif "/aweme/v1/web/aweme/favorite/" in u:
            j = resp.json()
            counter["favorite"] += len(j.get("aweme_list") or [])
            probe["favorite_tops"].append({k: j.get(k) for k in
                                           ("status_code", "has_more", "cursor")})
    except Exception:
        pass


TEXT = "() => document.body.innerText.replace(/\\n{2,}/g,'\\n').slice(0, 1200)"


class P:
    def evaluate(self, *a):
        pass


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False,
                                               viewport={"width": 1400, "height": 950},
                                               args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)

    print("== 收藏夹列表页 ==")
    page.goto(LIST_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    try:
        t = page.get_by_text("收藏夹", exact=True).first
        if t.count() and t.is_visible():
            t.click()
            page.wait_for_timeout(3000)
    except Exception:
        pass
    for _ in range(14):
        page.mouse.move(690, 500)
        page.mouse.wheel(0, 2600)
        page.wait_for_timeout(900)
    print("页面文字（前 700 字）:")
    print(page.evaluate(TEXT)[:700])

    s = sum(f["total"] for f in folders.values())
    print(f"\n收藏夹 {len(folders)} 个，标注总数合计 = {s}")
    print("各夹：")
    for cid, f in sorted(folders.items(), key=lambda x: -x[1]["total"]):
        print(f"   {f['total']:>4}  {f['name']}")

    print("\n== 收藏 tab（aweme/favorite 来源）==")
    page.goto(FAV_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    print("页面文字（前 700 字）:")
    print(page.evaluate(TEXT)[:700])
    for _ in range(6):
        page.mouse.move(690, 500)
        page.mouse.wheel(0, 2600)
        page.wait_for_timeout(900)

    print(f"\naweme/favorite 累计返回 {counter['favorite']} 条")
    print("favorite 响应顶层:", probe["favorite_tops"][:3])
    print("collects/list 响应顶层:", probe["list_tops"][:3])
    ctx.close()
