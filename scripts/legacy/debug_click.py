# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright

PROFILE = r"/browser_profile"

def on_response(resp):
    u = resp.url
    if "collects/video/list" in u or "aweme/favorite" in u:
        print("XHR:", u[:160], flush=True)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(PROFILE, headless=False,
                                               viewport={"width": 1380, "height": 900})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)
    page.goto("https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection",
              wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    # 滚两屏让卡片加载
    for i in range(4):
        page.mouse.move(690, 500)
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(1000)
    # 找卡片：含收藏夹名的元素
    card = page.locator("text=研生活，应该做什么").first
    print("卡片存在:", card.count(), flush=True)
    card.click()
    page.wait_for_timeout(4000)
    print("点击后 URL:", page.url, flush=True)
    # 滚动 feed
    for i in range(8):
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        try:
            page.mouse.move(690, 500)
            page.mouse.wheel(0, 3000)
        except Exception:
            pass
        page.wait_for_timeout(1000)
    print("滚动后 URL:", page.url, flush=True)
    ctx.close()
