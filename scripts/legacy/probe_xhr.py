# -*- coding: utf-8 -*-
"""只读探测：页面自身 XHR（点开收藏夹卡片 + 滚动）现在还能不能拿到视频数据。
不写 favorites.json，只打印统计。用于判断软限流是否解除。
用法：python probe_xhr.py [收藏夹名] [滚动轮数]
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "browser_profile"
LIST_URL = "https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection"

TARGET = sys.argv[1] if len(sys.argv) > 1 else "ai"
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 12

hits = []          # 每次 collects/video/list 响应的条数
folder_list = {}


def on_response(resp):
    u = resp.url
    try:
        if "/aweme/v1/web/collects/list/" in u:
            j = resp.json()
            for it in (j.get("collects_list") or []):
                cid = str(it.get("collects_id") or "")
                if cid:
                    folder_list[cid] = (it.get("collects_name") or "", int(it.get("total_number") or 0))
        elif "/aweme/v1/web/collects/video/list/" in u:
            j = resp.json()
            n = len(j.get("aweme_list") or [])
            hits.append(n)
            print(f"  [XHR] collects/video/list -> {n} 条 (has_more={j.get('has_more')})", flush=True)
    except Exception:
        pass


def main():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=False,
                                                   viewport={"width": 1380, "height": 900},
                                                   args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", on_response)
        cookies = {c["name"] for c in ctx.cookies()}
        print(f"登录态 sessionid: {'有' if 'sessionid' in cookies else '无'}", flush=True)

        page.goto(LIST_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        try:
            t = page.get_by_text("收藏夹", exact=True).first
            if t.count() > 0 and t.is_visible():
                t.click()
                page.wait_for_timeout(2500)
        except Exception:
            pass
        # 滚动列表页，先让收藏夹清单 XHR 跑起来
        for _ in range(25):
            page.mouse.move(690, 500)
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(600)
        print(f"收藏夹清单: {len(folder_list)} 个 / 总数 {sum(v[1] for v in folder_list.values())} 条", flush=True)

        # 点开目标卡片
        clicked = False
        for _ in range(40):
            try:
                loc = page.get_by_text(TARGET, exact=False)
                if loc.count() > 0:
                    el = loc.first
                    if el.is_visible():
                        el.click(timeout=5000)
                        clicked = True
                        break
            except Exception:
                pass
            try:
                page.mouse.move(690, 500)
                page.mouse.wheel(0, 2000)
            except Exception:
                pass
            page.wait_for_timeout(800)
        print(f"点开卡片 {TARGET!r}: {clicked}", flush=True)
        if clicked:
            page.wait_for_timeout(3000)
            for i in range(ROUNDS):
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    pass
                try:
                    page.mouse.move(690, 500)
                    page.mouse.wheel(0, 3000)
                except Exception:
                    pass
                page.wait_for_timeout(1500)
                print(f"  滚动 {i + 1}/{ROUNDS}，累计响应条数 {sum(hits)}", flush=True)

        print(f"\n结果：collects/video/list 共 {len(hits)} 次响应，累计 {sum(hits)} 条；"
              f"非零响应 {sum(1 for h in hits if h)} 次", flush=True)
        print("判定：" + ("页面 XHR 可用 ✅" if sum(hits) > 0 else "页面 XHR 也被限流 ❌"), flush=True)
        ctx.close()


if __name__ == "__main__":
    main()
