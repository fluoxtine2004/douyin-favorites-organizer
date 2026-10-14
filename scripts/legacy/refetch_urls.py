# -*- coding: utf-8 -*-
"""
补直链 + 转写：对 favorites.json 中 dl_failed 的视频
  用 Playwright 打开视频详情页，拦截 play_addr 接口拿【新鲜直链】
  → 更新 play_urls → 调用 process_batch 逻辑转写
用法：
  python scripts/refetch_urls.py [--limit 20]
"""
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "favorites.json"
PROFILE = ROOT / "browser_profile"


def main():
    limit = 20
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    data = json.loads(DATA.read_text(encoding="utf-8"))
    # 收集待补直链的视频（dl_failed 或 无有效直链）
    todo = []
    for f in data.get("folders", []):
        for v in f.get("videos", []):
            if v.get("transcript") or v.get("no_transcript"):
                continue
            if v.get("dl_failed_recently") or not v.get("play_urls"):
                todo.append(v)
    todo = todo[:limit]
    if not todo:
        print("没有需要补直链的视频。")
        return
    print(f"待补直链 {len(todo)} 条…")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE), headless=False,
            viewport={"width": 1380, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        ok = 0
        for i, v in enumerate(todo, 1):
            vid = v["id"]
            url = f"https://www.douyin.com/video/{vid}"
            print(f"[{i}/{len(todo)}] {vid} {v.get('title','')[:40]}", flush=True)
            found = []
            def on_resp(resp):
                try:
                    if "/aweme/v1/web/aweme/detail/" in resp.url:
                        j = resp.json()
                        aw = j.get("aweme_detail") or {}
                        vd = aw.get("video") or {}
                        play = (vd.get("play_addr") or {}).get("url_list") or []
                        for u in play:
                            if u not in found:
                                found.append(u)
                except Exception:
                    pass
            page.on("response", on_resp)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(5000)
                # 滚动触发加载
                for _ in range(3):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1500)
            except Exception as e:
                print(f"  打开失败: {e}", flush=True)
                page.remove_listener("response", on_resp)
                continue
            page.remove_listener("response", on_resp)
            if found:
                v["play_urls"] = found
                v.pop("dl_failed_recently", None)
                ok += 1
                print(f"  ✅ 拿到 {len(found)} 条新鲜直链", flush=True)
            else:
                print("  !! 未捕获到直链（可能视频已删/需要登录）", flush=True)
            DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

        print(f"\n补直链完成：成功 {ok} / {len(todo)}")
        ctx.close()


if __name__ == "__main__":
    main()
