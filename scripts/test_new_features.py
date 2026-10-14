# -*- coding: utf-8 -*-
"""验证本次新增的三个功能：时间排序切换 / 待办事项 / 侧栏每日推荐+可执行案例"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
errors = []

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1500, "height": 950})
    page.on("pageerror", lambda e: errors.append("PAGEERROR: " + str(e)))
    page.on("console", lambda m: errors.append("CONSOLE: " + m.text) if m.type == "error" else None)
    page.goto((ROOT / "dashboard.html").as_uri())
    page.wait_for_timeout(2000)

    # ---- 1. 侧栏每日推荐 + 可执行案例 ----
    print("== 1) 侧栏 ==")
    print("侧栏存在:", page.locator("#side").count())
    cards = page.locator(".side-card")
    print("侧栏卡片数:", cards.count())
    print("推荐视频标题:", page.locator(".side-v .sv-t").first.inner_text()[:40])
    print("推荐视频日期:", page.locator(".side-v .sv-d").first.inner_text()[:40])
    print("案例标题:", page.locator(".sc-title").first.inner_text()[:40])
    print("案例动作:", page.locator(".sc-act").first.inner_text()[:50])
    # 换一个
    before = page.locator(".side-v .sv-t").first.inner_text()
    page.locator(".side-card h4 .mini").first.click()
    page.wait_for_timeout(700)
    after = page.locator(".side-v .sv-t").first.inner_text()
    print("点「换一个」后标题变化:", before != after)

    # ---- 2. 排序：收藏时间 / 发布时间 ----
    print("\n== 2) 排序 ==")
    sel = page.locator(".toolbar select.sortsel")
    print("排序依据下拉选项:", sel.locator("option").all_inner_texts())
    print("默认选中:", sel.input_value())
    d1 = page.locator(".row .chip.date").first.inner_text()
    print("默认(收藏时间 新→旧) 首条:", d1)
    btn = page.locator(".toolbar button").first
    print("方向按钮:", btn.inner_text())
    btn.click(); page.wait_for_timeout(800)
    d2 = page.locator(".row .chip.date").first.inner_text()
    print("切到 旧→新 后首条:", d2, "| 已翻转:", d1 != d2)
    btn.click(); page.wait_for_timeout(700)
    # 切到发布时间
    sel.select_option("publish"); page.wait_for_timeout(900)
    d3 = page.locator(".row .chip.date").first.inner_text()
    print("切到「按发布时间」后首条:", d3, "| 标签已换:", "发布" in d3)
    sel.select_option("collect"); page.wait_for_timeout(900)
    print("切回收藏时间首条:", page.locator(".row .chip.date").first.inner_text())
    # 刷新后记忆
    page.reload(); page.wait_for_timeout(1800)
    print("刷新后排序依据仍为:", page.locator(".toolbar select.sortsel").input_value())

    # ---- 3. 待办事项 ----
    print("\n== 3) 待办 ==")
    page.locator("#todoInput").first.fill("测试待办：整理本周逐字稿")
    page.locator(".todo-add button").first.click()
    page.wait_for_timeout(700)
    print("侧栏待办条数:", page.locator("#side .todo-item").count())
    # 进待办页
    page.locator("nav button", has_text="待办").first.click()
    page.wait_for_timeout(700)
    print("待办页统计:", page.locator(".stat b").all_inner_texts()[:3])
    print("待办项数:", page.locator(".todo-box .todo-item").count())
    # 勾选
    page.locator(".todo-box input[type=checkbox]").first.check()
    page.wait_for_timeout(700)
    print("勾选后已完成统计:", page.locator(".stat b").all_inner_texts()[:3])
    # 从视频加入待办
    page.locator("nav button", has_text="全部").first.click()
    page.wait_for_timeout(600)
    page.locator(".row").first.click()
    page.wait_for_timeout(900)
    print("详情页有「加入待办」按钮:", page.locator("button", has_text="加入待办").count())
    page.locator(".d-actions button", has_text="加入待办").first.click()
    page.wait_for_timeout(800)
    print("侧栏待办条数(详情页):", page.locator("#side .todo-item").count())
    # 刷新后仍在
    page.reload(); page.wait_for_timeout(1800)
    page.locator("nav button", has_text="待办").first.click()
    page.wait_for_timeout(700)
    print("刷新后待办项数:", page.locator(".todo-box .todo-item").count())

    print("\nJS 报错:", errors[:5] if errors else "无")
    b.close()
