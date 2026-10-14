# -*- coding: utf-8 -*-
"""
抖音收藏抓取脚本 v3（保留收藏夹原有分类）
原理：Playwright 持久化浏览器（扫码一次，Cookie 复用），拦截 XHR 收集数据。
接口（2026-09-22 实测）：
  收藏夹列表:   /aweme/v1/web/collects/list/        （分页 cursor=0,10,20...）
  收藏夹内容:   /aweme/v1/web/collects/video/list/  （query: collects_id, cursor 翻页）
  ⚠ 不要监听 /aweme/v1/web/aweme/favorite/ —— 那是【点赞/喜欢】列表，不是收藏！
    之前误把它当"全部收藏并集"吸收进默认收藏，导致点赞视频混入数据源（2026-09-25 用户发现）。
关键经验：
  - collection_id URL 参数打开的是"全部收藏"，不是收藏夹；必须从列表页点击卡片打开 feed
  - feed 是同 URL 的 SPA 覆盖层，window.scrollTo + 鼠标滚轮 都能触发翻页
  - 视频归属以 URL 里的 collects_id 为准（不经 current_collect_id 猜测）
用法：
  python fetch_favorites.py [--skip-folders]   # --skip-folders 只抓列表与预览，不逐夹打开
"""
import json
import sys
import sys as _sys
_sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lockutil import acquire, release  # noqa
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "browser_profile"
DATA_DIR = ROOT / "data"
OUT_FILE = DATA_DIR / "favorites.json"

LOGIN_WAIT_SEC = 3600         # 等扫码登录最长时间
SCROLL_MAX = 80               # 每个页面最多滚动次数
SCROLL_IDLE_ROUNDS = 6        # 连续几次无新数据则认为加载完毕


# ---------------- 增量保留 ----------------

KEEP_FIELDS = ("transcript", "points", "frames", "frames_curated",
               "processed_at", "dl_failed_recently", "no_play_urls",
               "no_transcript", "no_frames")


def load_keep() -> dict:
    """读取上一次结果，按视频 id 保留已处理内容，避免重抓覆盖逐字稿"""
    keep = {}
    if not OUT_FILE.exists():
        return keep
    try:
        prev = json.loads(OUT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return keep
    for f in prev.get("folders", []):
        for v in f.get("videos", []):
            kv = {k: v[k] for k in KEEP_FIELDS if k in v}
            if kv:
                keep[v["id"]] = kv
    return keep


_KEEP: dict = {}

# ---------------- 数据收集 ----------------

collects: dict = {}   # collect_id -> {"id","name","total","videos":{aweme_id:video}}


def _find_dicts(obj, keys):
    """深度遍历，返回所有包含指定键的 dict"""
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
    """从 aweme 对象提取需要的字段"""
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
    """从响应 JSON 中吸收视频到指定收藏夹，返回新增数"""
    added = 0
    for aw in _find_dicts(j, ("aweme_id",)):
        if not isinstance(aw.get("video"), (dict, type(None))) and "desc" not in aw:
            continue  # 跳过嵌套误匹配
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
        # ⚠ 2026-09-25 修复：移除 /aweme/v1/web/aweme/favorite/ 分支
        # 该接口是【点赞/喜欢】列表，不是收藏；之前误吸收进默认收藏导致点赞混入。
        # 只保留 collects/ 系列（收藏夹）接口。
    except Exception:
        # 网络/解析偶发错误不致命
        pass


# ---------------- 页面操作 ----------------

def wait_login(page, ctx):
    """等待登录（cookie 出现 sessionid）"""
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
    """自动滚动直到数据加载完（窗口滚动 + 鼠标滚轮双保险）"""
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
    # 确保点开「收藏夹」子标签
    try:
        tab = page.get_by_text("收藏夹", exact=True).first
        if tab.count() > 0 and tab.is_visible():
            tab.click()
            page.wait_for_timeout(2500)
    except Exception:
        pass


def scroll_folder(page, cid, expected, label):
    """按接口给出的真实数量滚动：抓够 expected 就停，否则滚到不再新增"""
    total_now = lambda: len(collects.get(cid, {}).get("videos", {}))
    print(f"==> 滚动加载：{label}（目标 {expected or '?'} 条）", flush=True)
    prev = total_now()
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
        now = total_now()
        if expected and now >= expected:
            break
        if now == prev:
            idle += 1
            if idle >= SCROLL_IDLE_ROUNDS:
                break
        else:
            idle = 0
        prev = now
    got = total_now()
    flag = "✅" if (not expected or got >= expected) else f"⚠ 缺 {expected - got}"
    print(f"==> {label}：{got}/{expected or '?'} 条 {flag}", flush=True)


def click_folder_card(page, name, nth):
    """在列表页滚动查找名称卡片并点击（同名夹按 nth 序号），打开 feed"""
    for _ in range(60):
        try:
            loc = page.get_by_text(name, exact=False)
            if loc.count() > nth:
                el = loc.nth(nth)
                if el.is_visible():
                    el.click(timeout=5000)
                    return True
        except Exception:
            pass
        try:
            page.mouse.move(690, 500)
            page.mouse.wheel(0, 2000)
        except Exception:
            pass
        page.wait_for_timeout(800)
    return False


def save():
    """增量保存，防止中途崩溃丢数据（并保留已转写内容）"""
    for c in collects.values():
        for vid, v in c["videos"].items():
            kept = _KEEP.get(vid)
            if kept:
                for k, val in kept.items():
                    v.setdefault(k, val)
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
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    if not acquire("fetch_favorites"):
        return
    global _KEEP
    _KEEP = load_keep()
    skip_folders = "--skip-folders" in sys.argv
    DATA_DIR.mkdir(parents=True, exist_ok=True)

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

        # 2. 直接打开「收藏夹」列表页（⚠ 2026-09-25：不再打开"全部收藏/视频"点赞页）
        goto_list(page)
        scroll_to_load(page, "收藏夹列表")

        if not skip_folders:
            # 4. 逐个点击卡片打开 feed，滚动翻页拿全量
            processed = set()
            round_no = 0
            while True:
                order = [cid for cid in collects if cid not in ("0", "")]
                # 每个夹都点开翻页（列表页预览只给每夹 ~10 条，大夹会截断）
                pending = [cid for cid in order if cid not in processed]
                if not pending:
                    break
                round_no += 1
                print(f"==> 第 {round_no} 轮：待进入收藏夹 {len(pending)} 个", flush=True)
                for cid in pending:
                    processed.add(cid)
                    c = collects[cid]
                    # 同名收藏夹的序号（列表卡片顺序与接口返回顺序一致）
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
                        save()  # 每抓完一个收藏夹就落盘一次

        # 5. ⚠ 2026-09-25：移除"默认收藏 = 全部收藏并集 - 自定义夹"逻辑
        #    该逻辑依赖点赞接口 aweme/favorite，会把点赞当收藏；真"默认收藏"夹
        #    由 collects/list/ 接口正常提供（id=0 仅作哨兵）。

        # 6. 保存
        save()
        total = sum(len(c["videos"]) for c in collects.values())
        print(f"\n✅ 抓取完成：{len(collects)} 个收藏夹，{total} 条视频", flush=True)
        print(f"已保存到 {OUT_FILE}", flush=True)

        page.wait_for_timeout(3000)
        ctx.close()


    release()


if __name__ == "__main__":
    main()
