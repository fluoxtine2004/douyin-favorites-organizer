# -*- coding: utf-8 -*-
"""从真实页面流程里拦截收藏列表接口，dump 原始 aweme 字段，确认有无收藏时间"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "browser_profile"
LIST_URL = "https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection"

captured = []          # (url, raw_json)
collects_seen = {}     # cid -> name


def on_response(resp):
    u = resp.url
    if "/aweme/v1/web/collects/" not in u:
        return
    try:
        j = resp.json()
    except Exception:
        return
    captured.append((u, j))


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=True,
                                               viewport={"width": 1380, "height": 900})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)
    print("==> 打开收藏夹列表页…")
    page.goto(LIST_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    try:
        tab = page.get_by_text("收藏夹", exact=True).first
        if tab.count() > 0 and tab.is_visible():
            tab.click()
            page.wait_for_timeout(3000)
    except Exception as e:
        print("tab click:", e)

    print("已捕获接口响应:", len(captured))
    for u, j in captured:
        print("  ", u.split("?")[0], "→", list(j.keys())[:8] if isinstance(j, dict) else type(j))

    # 找一个收藏夹名点进去
    clicked = False
    for name in ["ai", "经验", "学习额外", "旅游攻略", "美食", "待看"]:
        loc = page.get_by_text(name, exact=False)
        if loc.count() > 0:
            try:
                loc.nth(0).click(timeout=4000)
                print("==> 已点开收藏夹:", name)
                clicked = True
                break
            except Exception:
                continue
    if not clicked:
        # 退而求其次：点第一个卡片
        try:
            page.locator("[class*=collect] [class*=card], a[href*='collect']").first.click(timeout=4000)
            print("==> 已点第一个卡片")
        except Exception as e:
            print("点卡片失败:", e)

    page.wait_for_timeout(5000)
    for _ in range(6):
        page.mouse.move(690, 500)
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(1200)

    print("\n滚动后累计捕获响应:", len(captured))
    vids = [(u, j) for u, j in captured if "/collects/video/list/" in u]
    print("其中视频列表响应:", len(vids))
    if not vids:
        print("⚠ 没抓到 video/list 响应；打印所有响应 URL：")
        for u, _ in captured[:20]:
            print("   ", u[:140])
    else:
        u, j = vids[0]
        aws = j.get("aweme_list") or []
        slim = {
            "extra": j.get("extra"), "log_pb": j.get("log_pb"),
            "cursor": j.get("cursor"), "has_more": j.get("has_more"),
            "items": [{"id": a.get("aweme_id"), "create_time": a.get("create_time"),
                       "desc": (a.get("desc") or "")[:40],
                       "collect_stat": a.get("collect_stat"),
                       "is_collects_selected": a.get("is_collects_selected")} for a in aws],
        }
        dump = ROOT / "data" / "_probe_raw_videolist.json"
        dump.write_text(json.dumps(slim, ensure_ascii=False, indent=1), encoding="utf-8")
        print("已精简存盘 →", dump)
        print("extra =", json.dumps(j.get("extra"), ensure_ascii=False)[:200])
        print("log_pb =", json.dumps(j.get("log_pb"), ensure_ascii=False)[:200])
        print("本页条数:", len(aws))
        import datetime as _dt
        for i, a in enumerate(aws):
            ct = a.get("create_time")
            print(f"  {i} {a.get('aweme_id')} 发布={_dt.datetime.fromtimestamp(ct):%Y-%m-%d} "
                  f"| {(a.get('desc') or '')[:28]}")
        ks = sorted(aws[0].keys()) if aws else []
        print("\n>>> 名字含 collect / fav 的键：")
        for k in ks:
            if "collect" in k.lower() or "fav" in k.lower():
                print(f"   {k} = {json.dumps(aws[0][k], ensure_ascii=False)[:70]}")
    ctx.close()
