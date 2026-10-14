# -*- coding: utf-8 -*-
"""找出「收藏」的扁平列表接口：逐个候选 URL，记录各自触发了哪些 API"""
from pathlib import Path
from playwright.sync_api import sync_playwright
import re

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "browser_profile"

CANDS = [
    "https://www.douyin.com/user/self?showTab=collection",
    "https://www.douyin.com/user/self?showTab=collect",
    "https://www.douyin.com/user/self?showTab=my_collection",
    "https://www.douyin.com/user/self?showTab=favorite_collection",
    "https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection",
]

hits = []


def on_response(resp):
    u = resp.url
    m = re.search(r"/aweme/v1/web/([\w/]+)/", u)
    if m:
        hits.append(m.group(1))


TABS = """() => {
  const out = [];
  document.querySelectorAll('span,div,a').forEach(el => {
    const t = (el.innerText||'').trim();
    if (['作品','喜欢','收藏','观看历史','稍后再看','我的预约','收藏夹','视频','音乐','合集','短剧'].includes(t)) {
      const r = el.getBoundingClientRect();
      if (r.width > 0) out.push({t, x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)});
    }
  });
  return out;
}"""

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False,
                                               viewport={"width": 1400, "height": 950},
                                               args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)

    for url in CANDS:
        hits.clear()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        for _ in range(4):
            page.mouse.move(690, 500)
            page.mouse.wheel(0, 2600)
            page.wait_for_timeout(1000)
        from collections import Counter
        c = Counter(hits)
        print(f"\n{url}\n   → {dict(c)}")

    # 明确点「收藏」大标签，再点「视频」子标签
    print("\n=== 手动点「收藏」→「视频」 ===")
    page.goto("https://www.douyin.com/user/self", wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    tabs = page.evaluate(TABS)
    print("  找到的标签:", tabs)
    for want in ("收藏",):
        for t in tabs:
            if t["t"] == want:
                hits.clear()
                page.mouse.click(t["x"], t["y"])
                page.wait_for_timeout(5000)
                from collections import Counter
                print(f"  点「{want}」→ {dict(Counter(hits))}")
                break
    tabs = page.evaluate(TABS)
    for t in tabs:
        if t["t"] == "视频":
            hits.clear()
            page.mouse.click(t["x"], t["y"])
            page.wait_for_timeout(5000)
            for _ in range(4):
                page.mouse.move(690, 500)
                page.mouse.wheel(0, 2600)
                page.wait_for_timeout(1000)
            from collections import Counter
            print(f"  点「视频」(在收藏下) → {dict(Counter(hits))}")
            break
    ctx.close()
