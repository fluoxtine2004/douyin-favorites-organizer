# -*- coding: utf-8 -*-
"""判定 /aweme/v1/web/aweme/favorite/ 到底是【收藏】还是【点赞】列表。
方法：打开若干视频详情页，直接读页面上「收藏」「点赞」按钮的激活状态。
对比两组：
  A 组 = 来自命名收藏夹（肯定是收藏）
  B 组 = 来自「默认收藏」（疑似来自 aweme/favorite 分支）
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "browser_profile"
SHOT = ROOT / "产出" / "_audit"
SHOT.mkdir(parents=True, exist_ok=True)

fav = json.loads((ROOT / "data" / "favorites.json").read_text(encoding="utf-8"))
A, B = [], []
for f in fav.get("folders", []):
    nm = f.get("name") or ""
    for v in f.get("videos", []):
        (B if nm == "默认收藏" else A).append((v["id"], nm, (v.get("title") or "")[:28]))

print(f"A 组（命名夹）{len(A)} 条   B 组（默认收藏）{len(B)} 条")
pick_a = [A[3], A[40], A[120]]
pick_b = B[:3]
print("A 抽样:", [(i, t) for i, _, t in pick_a])
print("B 抽样:", [(i, t) for i, _, t in pick_b])

# 从页面读按钮激活状态
READ = """() => {
  const out = [];
  document.querySelectorAll('[data-e2e], button, div[role=button]').forEach(el => {
    const t = (el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 24);
    const cls = (el.className || '').toString();
    const aria = el.getAttribute('aria-pressed') || el.getAttribute('aria-label') || '';
    if (/收藏|点赞|喜欢|分享|评论/.test(t) || /collect|like|digg|favorite/i.test(cls + ' ' + aria)) {
      out.push({t, cls: cls.slice(0, 120), aria, e2e: el.getAttribute('data-e2e') || ''});
    }
  });
  return out.slice(0, 40);
}"""

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False,
                                               viewport={"width": 1400, "height": 900},
                                               args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    for tag, group in (("A命名夹", pick_a), ("B默认收藏", pick_b)):
        for vid, nm, ti in group:
            try:
                page.goto(f"https://www.douyin.com/video/{vid}", wait_until="domcontentloaded")
                page.wait_for_timeout(6000)
                info = page.evaluate(READ)
                print(f"\n--- [{tag}] {vid} | {nm} | {ti}")
                seen = set()
                for it in info:
                    key = (it["t"], it["e2e"], it["aria"])
                    if key in seen:
                        continue
                    seen.add(key)
                    print(f"    text={it['t']!r:26s} e2e={it['e2e']:18s} aria={it['aria'][:30]:30s} cls={it['cls'][:80]}")
                page.screenshot(path=str(SHOT / f"{tag}_{vid}.png"))
            except Exception as e:
                print(f"--- [{tag}] {vid} 失败: {str(e)[:80]}")
    ctx.close()
print("\n截图 →", SHOT)
