# -*- coding: utf-8 -*-
"""一锤定音：从视频详情接口读 collect_stat / digg 等用户态标志，
对比 A 组（命名收藏夹 = 确定是收藏）与 B 组（默认收藏 = 疑似点赞）。"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "browser_profile"

fav = json.loads((ROOT / "data" / "favorites.json").read_text(encoding="utf-8"))
A, B = [], []
for f in fav.get("folders", []):
    nm = f.get("name") or ""
    for v in f.get("videos", []):
        (B if nm == "默认收藏" else A).append((v["id"], nm, (v.get("title") or "")[:26]))

pick = [("A·命名夹", A[3]), ("A·命名夹", A[60]), ("A·命名夹", A[200]),
        ("B·默认收藏", B[0]), ("B·默认收藏", B[1]), ("B·默认收藏", B[10])]

got = {}


def on_response(resp):
    if "/aweme/v1/web/aweme/detail/" in resp.url:
        try:
            j = resp.json()
            got["detail"] = j
        except Exception:
            pass


KEYS = ("collect", "fav", "digg", "like", "status", "is_")


def scan(o, path="", out=None, depth=0):
    if out is None:
        out = []
    if depth > 4:
        return out
    if isinstance(o, dict):
        for k, v in o.items():
            kl = k.lower()
            if any(s in kl for s in KEYS) and not isinstance(v, (dict, list)):
                out.append((path + "." + k, v))
            if isinstance(v, (dict, list)):
                scan(v, path + "." + k, out, depth + 1)
    elif isinstance(o, list):
        for i, v in enumerate(o[:5]):
            scan(v, f"{path}[{i}]", out, depth + 1)
    return out


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False,
                                               viewport={"width": 1400, "height": 950},
                                               args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)
    for tag, (vid, nm, ti) in pick:
        got.clear()
        try:
            page.goto(f"https://www.douyin.com/video/{vid}", wait_until="domcontentloaded")
            page.wait_for_timeout(7000)
        except Exception as e:
            print(f"[{tag}] {vid} 打开失败 {str(e)[:50]}")
            continue
        d = (got.get("detail") or {}).get("aweme_detail") or {}
        if not d:
            print(f"[{tag}] {vid} | {nm} | {ti} → 未捕获详情接口")
            continue
        hits = [(k, v) for k, v in scan(d) if not k.startswith(".aweme_detail.author")
                and "author." not in k]
        print(f"\n[{tag}] {vid} | {nm} | {ti}")
        shown = set()
        for k, v in hits:
            if k in shown:
                continue
            shown.add(k)
            print(f"    {k:52s} = {v}")
    ctx.close()
