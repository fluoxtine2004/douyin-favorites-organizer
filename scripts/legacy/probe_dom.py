# -*- coding: utf-8 -*-
"""只读探测 2：找出收藏夹卡片可靠的定位方式，并验证点击后能否翻页。
不写 favorites.json。
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "browser_profile"
LIST_URL = "https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection"
TARGET = sys.argv[1] if len(sys.argv) > 1 else "ai"
TARGET_ID = sys.argv[2] if len(sys.argv) > 2 else ""

seen = {}


def on_response(resp):
    u = resp.url
    try:
        if "/aweme/v1/web/collects/video/list/" in u:
            j = resp.json()
            m = re.search(r"collects_id=(\d+)", u)
            cid = m.group(1) if m else "?"
            n = len(j.get("aweme_list") or [])
            seen.setdefault(cid, []).append(n)
    except Exception:
        pass


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=False,
                                               viewport={"width": 1380, "height": 900},
                                               args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)
    page.goto(LIST_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    try:
        t = page.get_by_text("收藏夹", exact=True).first
        if t.count() > 0 and t.is_visible():
            t.click()
            page.wait_for_timeout(2500)
    except Exception:
        pass
    for _ in range(20):
        page.mouse.move(690, 500)
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(600)

    # 1) 找精确匹配的元素，打印其祖先卡片 HTML 片段
    print("=== exact 匹配元素 ===", flush=True)
    loc = page.get_by_text(TARGET, exact=True)
    print(f"exact 匹配数量: {loc.count()}", flush=True)
    if loc.count():
        try:
            html = loc.first.evaluate("el => { let n=el; for(let i=0;i<6&&n;i++){ n=n.parentElement; } return n ? n.outerHTML.slice(0,1200) : ''; }")
            print(html, flush=True)
        except Exception as e:
            print("outerHTML err:", e, flush=True)

    # 2) 找带 collects_id 的 DOM 节点（若有）
    print("\n=== 含 collects_id 的节点 ===", flush=True)
    info = page.evaluate("""() => {
      const out=[];
      document.querySelectorAll('*').forEach(el=>{
        for (const a of el.attributes||[]) {
          if (a.value && /\\d{15,20}/.test(a.value) && (a.name.includes('id')||a.name.includes('href')||a.name.includes('data'))) {
            out.push({tag:el.tagName, attr:a.name, val:a.value.slice(0,120), txt:(el.innerText||'').slice(0,40)});
            break;
          }
        }
      });
      return out.slice(0,25);
    }""")
    for x in info:
        print(" ", x, flush=True)

    # 3) 点击 exact 匹配元素并滚动，看是否触发该夹的翻页 XHR
    before = {k: sum(v) for k, v in seen.items()}
    if loc.count():
        try:
            loc.first.click(timeout=5000)
            print("\n已点击 exact 元素", flush=True)
        except Exception as e:
            print("\n点击失败:", e, flush=True)
        page.wait_for_timeout(3000)
        for i in range(10):
            page.mouse.move(690, 500)
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1500)
        after = {k: sum(v) for k, v in seen.items()}
        print(f"\n目标夹 id={TARGET_ID}", flush=True)
        if TARGET_ID:
            print(f"  目标夹点击前 {before.get(TARGET_ID, 0)} 条 → 点击后 {after.get(TARGET_ID, 0)} 条", flush=True)
        print("  各夹累计响应:", {k: v for k, v in sorted(after.items(), key=lambda kv: -kv[1])[:10]}, flush=True)
        print(f"  总响应条数: {sum(after.values())}", flush=True)

    ctx.close()
