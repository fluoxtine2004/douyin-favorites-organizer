# -*- coding: utf-8 -*-
"""
从 Playwright 持久化浏览器配置中导出 Cookie 为 Netscape 格式（供 yt-dlp 使用）。
先访问一次抖音首页刷新 s_v_web_id 等游客 Cookie，再全量导出。
用法：python export_cookies.py
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "browser_profile"
OUT_FILE = ROOT / "data" / "cookies.txt"


def main():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.douyin.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)  # 让站点刷新游客 cookie

        lines = ["# Netscape HTTP Cookie File"]
        n = 0
        for c in ctx.cookies():
            domain = c.get("domain", "")
            flag = "TRUE" if domain.startswith(".") else "FALSE"
            path = c.get("path") or "/"
            secure = "TRUE" if c.get("secure") else "FALSE"
            exp = int(c.get("expires") or -1)
            if exp <= 0:
                exp = 0
            name = str(c.get("name", "")).replace("\t", " ").replace("\n", " ")
            value = str(c.get("value", "")).replace("\t", " ").replace("\n", " ")
            lines.append("\t".join([domain, flag, path, secure, str(exp), name, value]))
            n += 1

        OUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"已导出 {n} 条 cookie -> {OUT_FILE}", flush=True)
        ctx.close()


if __name__ == "__main__":
    main()
