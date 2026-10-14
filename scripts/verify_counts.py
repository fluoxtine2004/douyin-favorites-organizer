# -*- coding: utf-8 -*-
"""核对抓取完整性：接口 total_number（真实作品数）vs 已抓数量"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
truth = {}   # collects_id -> (name, total_number)

def on_response(resp):
    if "/aweme/v1/web/collects/list/" in resp.url:
        try:
            j = resp.json()
        except Exception:
            return
        for it in (j.get("collects_list") or []):
            cid = str(it.get("collects_id") or it.get("collects_id_str") or "")
            if cid:
                truth[cid] = (it.get("collects_name") or "", it.get("total_number") or 0)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(ROOT / "browser_profile"), headless=False,
                                               viewport={"width": 1380, "height": 900})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)
    page.goto("https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection",
              wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    for i in range(40):   # 多滚几轮，把收藏夹列表全部翻完
        page.mouse.move(690, 500)
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(800)
    ctx.close()

data = json.loads((ROOT / "data" / "favorites.json").read_text(encoding="utf-8"))
# favorites.json 的收藏夹以【名字】为键（同名夹已按名合并），故同时按 name 与 id 对照
got_id, got_name = {}, {}
for f in data.get("folders", []):
    got_id[str(f.get("id"))] = len(f.get("videos", []))
    got_name[str(f.get("name"))] = len(f.get("videos", []))

# 同名夹：真实数量取其中最大值（同名夹内容取并集后，至少应覆盖最大的那个）
truth_name = {}
for cid, (name, total) in truth.items():
    if name:
        truth_name[name] = max(truth_name.get(name, 0), total)

print(f"接口返回收藏夹数: {len(truth)}（去重后名称 {len(truth_name)} 个）")
print(f"favorites.json：{len(data.get('folders', []))} 夹 / {sum(got_id.values())} 条")
print()
print(f"{'收藏夹':<26}{'真实':>6}{'已抓':>6}{'缺口':>6}")
gap_total = 0
miss = []
for name, total in sorted(truth_name.items(), key=lambda kv: -(kv[1] - got_name.get(kv[0], 0))):
    have = got_name.get(name, 0)
    gap = total - have
    if gap > 0:
        gap_total += gap
        miss.append((name, total, have, gap))
for name, total, have, gap in miss[:40]:
    print(f"{name[:24]:<26}{total:>6}{have:>6}{gap:>6}")
print(f"\n缺口合计: {gap_total} 条（{len(miss)} 个夹未抓全）")
print(f"真实总作品数(按夹求和, 含跨夹重复): {sum(t for _, t in truth.values())}")
