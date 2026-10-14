# -*- coding: utf-8 -*-
"""真实渲染验证：浏览器打开 dashboard.html，确认列表页与详情页能正常渲染"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
errors = []

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1400, "height": 950})
    page.on("pageerror", lambda e: errors.append("PAGEERROR: " + str(e)))
    page.on("console", lambda m: errors.append("CONSOLE: " + m.text) if m.type == "error" else None)
    page.goto((ROOT / "dashboard.html").as_uri())
    page.wait_for_timeout(2500)

    rows = page.locator(".row").count()
    print(f"列表卡片数: {rows}")
    if page.locator("h1").count():
        print(f"标题: {page.locator('h1').first.inner_text()[:40]}")
    if rows:
        print(f"统计数字: {page.locator('.stat b').all_inner_texts()[:4]}")
        # 点进第一条
        page.locator(".row").first.click()
        page.wait_for_timeout(1500)
        print(f"详情页存在: {page.locator('.detail').count()}")
        if page.locator(".d-title").count():
            print(f"详情标题: {page.locator('.d-title').first.inner_text()[:48]}")
        if page.locator(".sum-box").count():
            print(f"短总结: {page.locator('.sum-box').first.inner_text()[:70]}")
        print(f"时间轴节点: {page.locator('.tl-item').count()}")
        print(f"截图元素: {page.locator('.tl-body img').count()}")
        # 测分类编辑（大类/收藏夹均为 datalist 输入框，非 select）
        if page.locator("#sel-major").count():
            opts = page.locator("#major-list option").all_inner_texts()
            page.fill("#sel-major", opts[1] if len(opts) > 1 else (opts[0] if opts else "待归类"))
            page.fill("#inp-folder", "我的测试分类")
            page.locator(".tag-edit button").first.click()
            page.wait_for_timeout(900)
            print(f"大类下拉可选项: {opts[:5]}")
            print(f"改后大类标签: {page.locator('.d-meta .chip.major').first.inner_text()}")
            print(f"改后收藏夹标签: {page.locator('.d-meta .chip.folder').first.inner_text()}")
            # 恢复自动
            page.locator(".tag-edit button.ghost").first.click()
            page.wait_for_timeout(600)
            print(f"恢复后收藏夹: {page.locator('.d-meta .chip.folder').first.inner_text()}")
        # 测筛选：点「重要」标签
        page.locator(".back").first.click()
        page.wait_for_timeout(800)
        print(f"返回列表后卡片数: {page.locator('.row').count()}")
        # 测搜索
        page.fill("#q", "Obsidian")
        page.wait_for_timeout(800)
        print(f"搜索 Obsidian 命中: {page.locator('.row').count()}")
    print("JS 报错:", errors[:3] if errors else "无")
    b.close()
