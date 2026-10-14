# -*- coding: utf-8 -*-
"""快速核对：列表页卡片显示的作品数 vs 已抓数量（文本抓回 Python 解析，避免 JS 转义坑）"""
import json, re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT / "data" / "favorites.json").read_text(encoding="utf-8"))
captured = {}
for f in data["folders"]:
    captured[f["name"]] = captured.get(f["name"], 0) + len(f.get("videos", []))

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(ROOT / "browser_profile"), headless=True,
                                               viewport={"width": 1380, "height": 900})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection",
              wait_until="domcontentloaded")
    page.wait_for_timeout(4500)
    for i in range(20):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.mouse.move(690, 500)
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(600)
    texts = page.evaluate("() => Array.from(document.querySelectorAll('div')).map(e => e.innerText).filter(t => t && t.includes('个作品'))")
    ctx.close()

pairs = []
for t in texts:
    parts = [x.strip() for x in (t or "").split("\n") if x.strip()]
    for i, pt in enumerate(parts):
        m = re.fullmatch(r"(\d+)\s*个作品", pt)
        if m and i > 0:
            name = parts[i - 1]
            pairs.append((name, int(m.group(1))))

seen = set()
miss = 0
print(f"解析到卡片 {len(pairs)} 个")
for name, n in pairs:
    if (name, n) in seen:
        continue
    seen.add((name, n))
    have = captured.get(name, -1)
    if have < 0:
        print(f"  ?  {name}: 显示 {n} / 未在抓取结果中")
        miss += n
    elif have < n:
        print(f"  缺 {name}: 显示 {n} / 已抓 {have}")
        miss += n - have
print(f"\n合计缺口: {miss} 条")
