# -*- coding: utf-8 -*-
"""给三个新功能出截图"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOT = ROOT / "产出"
SHOT.mkdir(exist_ok=True)

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1600, "height": 1000})
    page.goto((ROOT / "dashboard.html").as_uri())
    page.wait_for_timeout(2200)
    # 列表页 + 侧栏
    page.screenshot(path=str(SHOT / "新功能_列表与侧栏.png"))
    # 排序切换
    page.locator(".toolbar button").first.click()
    page.wait_for_timeout(900)
    page.screenshot(path=str(SHOT / "新功能_时间排序切换.png"))
    page.locator(".toolbar button").first.click()
    page.wait_for_timeout(700)
    # 详情页（含加入待办按钮 + 侧栏仍在）
    page.locator(".row").nth(2).click()
    page.wait_for_timeout(1200)
    page.screenshot(path=str(SHOT / "新功能_详情页与加入待办.png"))
    # 待办页
    page.locator("nav button", has_text="待办").first.click()
    page.wait_for_timeout(900)
    for t in ["读《对抗脑腐》并写下自己的 4 项自测分数",
              "给毕业论文综述建 NotebookLM 对话",
              "整理多洛米蒂的交通+预算+最佳季节"]:
        page.locator("#todoInput").first.fill(t)
        page.locator(".todo-add button").first.click()
        page.wait_for_timeout(400)
    page.locator(".todo-box input[type=checkbox]").nth(1).check()
    page.wait_for_timeout(900)
    page.screenshot(path=str(SHOT / "新功能_待办事项.png"))
    b.close()
    print("截图完成 →", SHOT)
