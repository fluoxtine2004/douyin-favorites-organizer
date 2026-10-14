# -*- coding: utf-8 -*-
"""登录态预检 v2（headless）：用与正式抓取相同的完整参数调用 collects/list，区分未登录/参数错误。
有效 → exit 0；未登录 → exit 3；其他 → exit 4。
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "browser_profile"
REST = ("device_platform=webapp&aid=6383&channel=channel_pc_web&pc_client_type=1"
        "&version_code=170400&version_name=17.4.0&cookie_enabled=true"
        "&screen_width=1380&screen_height=900&browser_language=zh-CN"
        "&browser_platform=Win32&browser_name=Chrome&browser_version=130.0.0.0")
URL = f"https://www.douyin.com/aweme/v1/web/collects/list/?{REST}"
JS = """async ([url]) => {
  try {
    const r = await fetch(url, {credentials:'include'});
    const t = await r.text();
    let j; try { j = JSON.parse(t); } catch(e) { return {raw: t.slice(0,80)}; }
    return {code: j.status_code, has_list: Array.isArray(j.collects_list)};
  } catch(e) { return {err: String(e).slice(0,120)}; }
}"""


def main():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=True,
            viewport={"width": 1380, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.douyin.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        try:
            res = page.evaluate(JS, [URL])
            print("完整参数探测: " + str(res)[:200], flush=True)
            code = res.get("code")
            # 0=成功(已登录)；4=未登录/需验证；其他码按返回处理
            if code == 0 or res.get("has_list"):
                print("LOGIN_OK", flush=True)
                ctx.close()
                return 0
            print(f"NOT_LOGGED_IN (code={code})", flush=True)
            ctx.close()
            return 3
        except Exception as e:
            print(f"PROBE_FAILED: {e}", flush=True)
            ctx.close()
            return 4


if __name__ == "__main__":
    sys.exit(main())
