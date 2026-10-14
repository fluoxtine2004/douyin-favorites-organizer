# -*- coding: utf-8 -*-
"""
采集「收藏先后顺序」——抖音网页接口不提供收藏时间戳，但
/aweme/v1/web/collects/video/list/ 是按【收藏时间倒序】返回的，
所以「视频在接口里的出现次序」就是真实的收藏先后。

输出 data/collect_order.json：
  {
    "fetched_at": "...",
    "folders": { cid: {"name": str, "ids": [id...]} },   # ids[0] = 该夹最新收藏
    "union":   [id...]                                    # 全部收藏（listcollection，全局最新在前）
  }

⚠ 数据源纪律：只用【收藏】系列接口
   - /aweme/v1/web/collects/video/list/    收藏夹内视频（按收藏时间倒序）
   - /aweme/v1/web/aweme/listcollection/   全部收藏扁平列表（按收藏时间倒序）
  绝不使用 /aweme/v1/web/aweme/favorite/ —— 那是【点赞/喜欢】，不是收藏。
  入库护栏：aweme.collect_stat=0 → 我没收藏 → 跳过。
用法：python fetch_collect_order.py [--only 夹名1,夹名2] [--fast]
"""
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "browser_profile"
OUT = ROOT / "data" / "collect_order.json"
LIST_URL = "https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection"
FAV_URL = "https://www.douyin.com/user/self?showTab=favorite_collection"

SCROLL_MAX = 80
SCROLL_IDLE_ROUNDS = 6

collects = {}      # cid -> {"name","total","ids":[]}
order_seen = {}    # cid -> set
union_ids = []
union_seen = set()


def log(m):
    print(m, flush=True)


def _find_dicts(obj, key):
    out = []
    if isinstance(obj, dict):
        if key in obj:
            out.append(obj)
        for v in obj.values():
            out.extend(_find_dicts(v, key))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_find_dicts(v, key))
    return out


def ensure(cid, name=""):
    if cid not in collects:
        collects[cid] = {"name": name or cid, "total": 0, "ids": []}
        order_seen[cid] = set()
    if name:
        collects[cid]["name"] = name
    return collects[cid]


def absorb(j, cid):
    """按响应顺序记录 id；已记录的跳过（同一 id 不重复占位）"""
    c = ensure(cid)
    n = 0
    for a in (j.get("aweme_list") or []):
        cs = a.get("collect_stat")
        if cs is not None:
            try:
                if int(cs) == 0:      # 🛡 没收藏 → 跳过
                    continue
            except Exception:
                pass
        v = str(a.get("aweme_id") or "")
        if v and v not in order_seen[cid]:
            order_seen[cid].add(v)
            c["ids"].append(v)
            n += 1
    return n


def absorb_union(j):
    n = 0
    for a in (j.get("aweme_list") or []):
        # 🛡 收藏护栏：collect_stat=0 → 我没收藏，跳过（防点赞混入）
        cs = a.get("collect_stat")
        if cs is not None:
            try:
                if int(cs) == 0:
                    continue
            except Exception:
                pass
        v = str(a.get("aweme_id") or "")
        if v and v not in union_seen:
            union_seen.add(v)
            union_ids.append(v)
            n += 1
    return n


def on_response(resp):
    u = resp.url
    try:
        if "/aweme/v1/web/collects/list/" in u:
            j = resp.json()
            for d in _find_dicts(j, "collect_id") + _find_dicts(j, "collects_id"):
                cid = str(d.get("collect_id") or d.get("collects_id") or "")
                if cid:
                    nm = d.get("name") or d.get("collects_name") or ""
                    tt = d.get("total_number") or d.get("total_count") or d.get("video_count")
                    c = ensure(cid, nm)
                    if tt:
                        c["total"] = int(tt)
        elif "/aweme/v1/web/collects/video/list/" in u:
            q = parse_qs(urlparse(u).query)
            cid = str((q.get("collects_id") or q.get("collect_id") or [""])[0]) or "0"
            absorb(resp.json(), cid)
        elif "/aweme/v1/web/aweme/favorite/" in u:
            # ⚠ 这是【点赞/喜欢】列表，不是收藏！
            #    历史 bug：曾用它当「全部收藏并集」，导致 20 条点赞被当成「最近收藏」，
            #    污染了收藏时间排序（2026-10-07 用户发现）。这里显式忽略。
            pass
        elif "/aweme/v1/web/aweme/listcollection/" in u:
            # 「全部收藏」扁平列表（真实收藏，按收藏时间倒序）→ 全局最近收藏次序
            absorb_union(resp.json())
    except Exception:
        pass


def wheel(page, n=1, dy=3000, pause=1.3):
    for _ in range(n):
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        try:
            page.mouse.move(690, 500)
            page.mouse.wheel(0, dy)
        except Exception:
            pass
        page.wait_for_timeout(int(pause * 1000))


def goto_list(page):
    page.goto(LIST_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    try:
        t = page.get_by_text("收藏夹", exact=True).first
        if t.count() > 0 and t.is_visible():
            t.click()
            page.wait_for_timeout(2500)
    except Exception:
        pass


def click_card(page, name, nth):
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


def scroll_folder(page, cid, expected, label):
    cnt = lambda: len(order_seen.get(cid, ()))
    prev, idle = cnt(), 0
    for _ in range(SCROLL_MAX):
        wheel(page, 1, 3000, 1.5)
        now = cnt()
        if expected and now >= expected:
            break
        if now == prev:
            idle += 1
            if idle >= SCROLL_IDLE_ROUNDS:
                break
        else:
            idle = 0
        prev = now
    got = cnt()
    flag = "✅" if (not expected or got >= expected) else f"⚠ 缺 {expected - got}"
    log(f"    {label}: {got}/{expected or '?'} {flag}")
    return got


def save():
    out = {
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "folders": {cid: {"name": c["name"], "ids": c["ids"]} for cid, c in collects.items()},
        "union": union_ids,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    only = None
    fast = "--fast" in sys.argv          # 只取列表页预览 + 并集（约 1 分钟）
    for i, a in enumerate(sys.argv):
        if a == "--only" and i + 1 < len(sys.argv):
            only = set(sys.argv[i + 1].split(","))
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False, viewport={"width": 1380, "height": 900},
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", on_response)

        # A. 列表页：拿到每个夹的首页预览（= 该夹最近收藏的一批，有顺序）
        log("==> A. 收藏夹列表 + 每夹首页预览（含顺序）…")
        goto_list(page)
        wheel(page, 25, 2500, 0.8)
        log(f"    已知 {len(collects)} 个夹；带顺序视频 {sum(len(c['ids']) for c in collects.values())} 条")

        # B. 全部收藏（listcollection）——全局最新收藏次序
        log("==> B. 全部收藏（listcollection）…")
        page.goto(FAV_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3500)
        try:
            t = page.get_by_text("视频", exact=True).first
            if t.count() > 0 and t.is_visible():
                t.click()
                page.wait_for_timeout(2500)
        except Exception:
            pass
        wheel(page, 30, 3000, 1.0)
        log(f"    全部收藏 {len(union_ids)} 条")

        if fast:
            save()
            log(f"\n✅ （--fast）{len(collects)} 个夹 / 带顺序 "
                f"{sum(len(c['ids']) for c in collects.values())} 条 / 并集 {len(union_ids)} 条")
            log(f"已保存 → {OUT}")
            ctx.close()
            return

        # C. 逐夹点开翻页补齐
        cid_order = [c for c in collects if c not in ("0", "")]
        pending = [c for c in cid_order if (not only or collects[c]["name"] in only)]
        log(f"==> C. 逐夹点开翻页：{len(pending)} 个夹")
        for i, cid in enumerate(pending, 1):
            c = collects[cid]
            need = int(c.get("total") or 0) - len(c["ids"])
            if need <= 0:
                continue
            nth = sum(1 for x in cid_order[:cid_order.index(cid)]
                      if collects[x]["name"] == c["name"])
            log(f"  [{i}/{len(pending)}] {c['name']} (id={cid}, 同名第{nth+1}) 缺 {need} 条")
            try:
                goto_list(page)
                if not click_card(page, c["name"], nth):
                    log("    !! 找不到卡片，跳过")
                    continue
                page.wait_for_timeout(2500)
                scroll_folder(page, cid, int(c.get("total") or 0), c["name"])
            except Exception as e:
                log(f"    !! 失败跳过：{str(e)[:60]}")
            save()

        save()
        tot = sum(len(c["ids"]) for c in collects.values())
        log(f"\n✅ 完成：{len(collects)} 个夹 / 带顺序 {tot} 条 / 并集 {len(union_ids)} 条")
        log(f"已保存 → {OUT}")
        page.wait_for_timeout(1500)
        ctx.close()


if __name__ == "__main__":
    main()
