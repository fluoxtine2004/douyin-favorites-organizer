# -*- coding: utf-8 -*-
"""
抖音收藏【干净重抓】脚本（2026-09-25 新增）
目的：修复 fetch_favorites.py 误把【点赞】当【收藏】混入数据源的问题，全新起跑。

与 fetch_favorites.py 的区别：
  1. 只监听 collects/ 系列接口（收藏夹），绝不碰 aweme/favorite（点赞）接口
  2. 不增量、不保留旧数据 —— 彻底清除点赞残留
  3. 先写临时文件，抓取量达到预期（≥60%）才覆盖正式 favorites.json
  4. 默认不自动删除旧 favorites.json（保险），用 --replace 才覆盖

用法：
  python fetch_favorites_clean.py            # 输出到 favorites.clean.json（不覆盖正式）
  python fetch_favorites_clean.py --replace  # 验证合格后覆盖正式 favorites.json
"""
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "browser_profile"
DATA_DIR = ROOT / "data"
CLEAN_OUT = DATA_DIR / "favorites.clean.json"
FINAL_OUT = DATA_DIR / "favorites.json"

LOGIN_WAIT_SEC = 3600
SCROLL_MAX = 80
SCROLL_IDLE_ROUNDS = 6

# 抓取量低于预期总收藏数的这个比例 → 判定失败，不覆盖
MIN_RATIO = 0.60

collects: dict = {}   # collect_id -> {"id","name","total","videos":{aweme_id:video}}


def _find_dicts(obj, keys):
    out = []
    if isinstance(obj, dict):
        if any(k in obj for k in keys):
            out.append(obj)
        for v in obj.values():
            out.extend(_find_dicts(v, keys))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_find_dicts(v, keys))
    return out


def safe_int(x, default=0):
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def fmt_duration(ms):
    try:
        s = int(ms) // 1000
        return f"{s // 60}:{s % 60:02d}"
    except Exception:
        return ""


def parse_aweme(aw):
    vid = str(aw.get("aweme_id") or aw.get("id") or "")
    if not vid:
        return None
    author = aw.get("author") or {}
    video = aw.get("video") or {}
    cover = ""
    try:
        cover = (video.get("cover") or {}).get("url_list", [""])[0]
    except Exception:
        pass
    play_urls = []
    try:
        play_urls = list((video.get("play_addr") or {}).get("url_list") or [])
        for br in (video.get("bit_rate") or []):
            for u in (br.get("play_addr") or {}).get("url_list") or []:
                if u not in play_urls:
                    play_urls.append(u)
    except Exception:
        pass
    stats = aw.get("statistics") or {}
    return {
        "id": vid,
        "title": (aw.get("desc") or "").strip() or "(无标题)",
        "url": f"https://www.douyin.com/video/{vid}",
        "cover": cover,
        "play_urls": play_urls,
        "author": author.get("nickname") or "",
        "duration": fmt_duration(video.get("duration") or aw.get("duration") or 0),
        "digg": safe_int(stats.get("digg_count")),
        "collect_count": safe_int(stats.get("collect_count")),
        "create_time": safe_int(aw.get("create_time")),
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def ensure_collect(cid, name="", total=None):
    if cid not in collects:
        collects[cid] = {"id": cid, "name": name or ("默认收藏" if cid in ("0", "") else cid),
                         "total": total, "videos": {}}
    c = collects[cid]
    if name:
        c["name"] = name
    if total is not None:
        c["total"] = total
    return c


def absorb_videos(j, target_cid):
    added = 0
    for aw in _find_dicts(j, ("aweme_id",)):
        if not isinstance(aw.get("video"), (dict, type(None))) and "desc" not in aw:
            continue
        v = parse_aweme(aw)
        if not v:
            continue
        c = ensure_collect(target_cid)
        if v["id"] not in c["videos"]:
            c["videos"][v["id"]] = v
            added += 1
    return added


def on_response(resp):
    url = resp.url
    try:
        # ⚠ 只处理收藏夹系列接口；aweme/favorite（点赞）绝不处理
        if "/aweme/v1/web/collects/list/" in url:
            j = resp.json()
            for d in _find_dicts(j, ("collect_id", "collects_id")):
                cid = str(d.get("collect_id") or d.get("collects_id") or "")
                if not cid:
                    continue
                nm = d.get("name") or d.get("collects_name") or ""
                tt = d.get("total_number") or d.get("total_count") or d.get("video_count")
                ensure_collect(cid, nm, safe_int(tt))
        elif "/aweme/v1/web/collects/video/list/" in url:
            q = parse_qs(urlparse(url).query)
            cid = str((q.get("collects_id") or q.get("collect_id") or [""])[0])
            added = absorb_videos(resp.json(), cid or "0")
            if added:
                print(f"  [视频] collect={collects.get(cid, {}).get('name', cid)} 新增 {added} 条", flush=True)
        # else: 忽略（含点赞接口 aweme/favorite）
    except Exception:
        pass


# ---------------- 页面操作（复制自 fetch_favorites.py，已移除点赞页步骤） ----------------

def wait_login(page, ctx):
    print("==> 检查登录状态…", flush=True)
    deadline = time.time() + LOGIN_WAIT_SEC
    told = False
    while time.time() < deadline:
        cookies = {c["name"] for c in ctx.cookies()}
        if "sessionid" in cookies:
            print("==> 已登录（Cookie 有效）", flush=True)
            return True
        if not told:
            print("==> 未登录：请在弹出的浏览器窗口中用【手机抖音 App 扫码】登录。", flush=True)
            told = True
        page.wait_for_timeout(2000)
    return False


def scroll_to_load(page, label):
    print(f"==> 滚动加载：{label}", flush=True)
    last_count = sum(len(c["videos"]) for c in collects.values())
    idle = 0
    for i in range(SCROLL_MAX):
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        try:
            page.mouse.move(690, 500)
            page.mouse.wheel(0, 3000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        now_count = sum(len(c["videos"]) for c in collects.values())
        if now_count == last_count:
            idle += 1
            if idle >= SCROLL_IDLE_ROUNDS:
                break
        else:
            idle = 0
            last_count = now_count
    print(f"==> 滚动完成：{label}（累计 {len(collects)} 个收藏夹，"
          f"{sum(len(c['videos']) for c in collects.values())} 条视频）", flush=True)


LIST_URL = "https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection"


def goto_list(page):
    page.goto(LIST_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    try:
        tab = page.get_by_text("收藏夹", exact=True).first
        if tab.count() > 0 and tab.is_visible():
            tab.click()
            page.wait_for_timeout(2500)
    except Exception:
        pass


def click_folder_card(page, name, nth):
    """点击列表页第 nth 个同名收藏夹卡片"""
    try:
        cards = page.get_by_text(name, exact=True)
        card = cards.nth(nth)
        if card.count() == 0 or not card.is_visible():
            return False
        card.click()
        page.wait_for_timeout(1500)
        return True
    except Exception:
        return False


def scroll_folder(page, cid, expected, name):
    last_count = len(collects[cid]["videos"])
    idle = 0
    for i in range(SCROLL_MAX):
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        try:
            page.mouse.move(690, 500)
            page.mouse.wheel(0, 3000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        now = len(collects[cid]["videos"])
        if now == last_count:
            idle += 1
            if idle >= SCROLL_IDLE_ROUNDS or now >= expected:
                break
        else:
            idle = 0
            last_count = now
    print(f"  → {name}: {last_count}/{expected}", flush=True)


def save_to(path):
    out = {
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_videos": sum(len(c["videos"]) for c in collects.values()),
        "folders": [
            {**{k: v for k, v in c.items() if k != "videos"},
             "video_count": len(c["videos"]),
             "videos": list(c["videos"].values())}
            for c in collects.values()
        ],
    }
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    replace = "--replace" in sys.argv
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1380, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", on_response)

        # 1. 打开抖音首页（若未登录会显示登录二维码）
        page.goto("https://www.douyin.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        if not wait_login(page, ctx):
            print("!! 等待登录超时，未抓取任何数据。下次再运行本脚本扫码即可。", flush=True)
            ctx.close()
            return

        # 2. 直接打开收藏夹列表页（不碰点赞页）
        goto_list(page)
        scroll_to_load(page, "收藏夹列表")

        # 3. 逐个点击卡片打开 feed，滚动翻页拿全量
        processed = set()
        round_no = 0
        while True:
            order = [cid for cid in collects if cid not in ("0", "")]
            pending = [cid for cid in order if cid not in processed]
            if not pending:
                break
            round_no += 1
            print(f"==> 第 {round_no} 轮：待进入收藏夹 {len(pending)} 个", flush=True)
            for cid in pending:
                processed.add(cid)
                c = collects[cid]
                nth = sum(1 for x in order[:order.index(cid)]
                          if collects[x]["name"] == c["name"])
                print(f"==> 打开收藏夹：{c['name']} (id={cid}, 同名第{nth + 1}个)", flush=True)
                try:
                    goto_list(page)
                    if not click_folder_card(page, c["name"], nth):
                        print("  !! 找不到卡片，跳过", flush=True)
                        continue
                    page.wait_for_timeout(2500)
                    expected = int(collects[cid].get("total") or 0)
                    scroll_folder(page, cid, expected, c["name"])
                except Exception as e:
                    print(f"  !! 收藏夹处理失败，跳过：{e}", flush=True)
                finally:
                    save_to(CLEAN_OUT)

        # 4. 保存到临时文件
        save_to(CLEAN_OUT)
        total = sum(len(c["videos"]) for c in collects.values())
        declared = sum(int(c.get("total") or 0) for c in collects.values())
        print(f"\n✅ 抓取完成：{len(collects)} 个收藏夹，{total} 条视频（收藏夹标注总数 {declared}）", flush=True)

        # 5. 质量校验：低于预期 60% 视为失败，不覆盖正式文件
        if declared > 0 and total < declared * MIN_RATIO:
            print(f"!! 抓取量 {total} < 标注总数 {declared} × {MIN_RATIO}，判定失败，不覆盖正式文件", flush=True)
            ctx.close()
            sys.exit(1)
        if total == 0:
            print("!! 抓取量为 0，判定失败，不覆盖正式文件", flush=True)
            ctx.close()
            sys.exit(1)

        print(f"临时文件：{CLEAN_OUT}", flush=True)
        if replace:
            # 备份旧的再覆盖
            from shutil import copy2
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            bk = DATA_DIR / f"_backup" / f"favorites.before_clean_{ts}.json"
            bk.parent.mkdir(parents=True, exist_ok=True)
            if FINAL_OUT.exists():
                copy2(FINAL_OUT, bk)
                print(f"已备份旧 favorites.json → {bk}", flush=True)
            FINAL_OUT.write_text(CLEAN_OUT.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"✅ 已覆盖正式文件：{FINAL_OUT}", flush=True)
        else:
            print("（未使用 --replace，正式 favorites.json 未改动）", flush=True)

        page.wait_for_timeout(3000)
        ctx.close()


if __name__ == "__main__":
    main()
