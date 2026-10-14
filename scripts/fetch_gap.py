# -*- coding: utf-8 -*-
"""补齐收藏缺口 v1.1（页面自身签名 XHR 版）

背景：raw fetch('/aweme/v1/web/collects/video/list/') 被软限流（全部返回空列表），
      但「页面自己发的」签名请求完全正常。因此本脚本不用 raw fetch，而是：
  A. 打开收藏夹列表页并滚动 → 监听页面 XHR 拿到 73 个夹的清单(id/name/total) 与每夹首页预览
  B. 对「预览不足 total」的夹，按缺口从大到小：goto 列表页 → get_by_text(名称, exact=True) 点开卡片
     → 滚动翻页，直到条数 >= total 或连续无新增
  C. 按【收藏夹名】合并（重名夹并集，与现有 favorites.json 结构一致）。
     先用上次 favorites.json 的每个夹「预置」已有视频（只增不减），再用新抓到的覆盖同 id 记录
     （保留 transcript/points/frames 等已处理字段）。

安全：先备份；每抓完一个夹就落盘一次；结果总数骤降（< 上次 90%）拒绝覆盖。

⚠ 数据源纪律（2026-10-07 加固）：
  - 只吸收【收藏】接口：collects/list、collects/video/list、aweme/listcollection
  - 绝不吸收 /aweme/v1/web/aweme/favorite/ —— 那是【点赞/喜欢】列表。
    它曾在 2026-09-25、2026-10-07 两次污染知识库（被用户发现）。
  - 入库护栏：aweme.collect_stat=0（我没收藏）一律跳过。
用法：
  python fetch_gap.py                 # 全量补
  python fetch_gap.py --limit 5       # 只补缺口最大的 5 个夹（可多轮执行）
  python fetch_gap.py --plan          # 只列清单，不抓不写
"""
import json
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))
from lockutil import acquire, release  # noqa
from playwright.sync_api import sync_playwright
from fetch_favorites import parse_aweme  # noqa

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "browser_profile"
OUT = ROOT / "data" / "favorites.json"
BACKUP_DIR = ROOT / "data" / "_backup"
LIST_URL = "https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection"
FAV_URL = "https://www.douyin.com/user/self?showTab=favorite_collection"

KEEP = ("transcript", "points", "frames", "frames_curated", "captured_at",
        "segments", "raw_segments", "summary", "title_clean", "is_new",
        "processed_at", "dl_failed_recently", "no_play_urls", "no_transcript",
        "no_frames")

SCROLL_IDLE = 3
SCROLL_LIST = 30
SCROLL_MAX_ONE = 30     # 单个卡片内最多滚动轮数
MAX_OCC = 1             # 同名卡片最多尝试几个（--deep 时提升）

collects = {}        # cid -> {"name","total","videos":{id:v}}


def log(m):
    print(m, flush=True)


def absorb(j, cid):
    added = 0
    for aw in (j.get("aweme_list") or []):
        # 🛡 收藏护栏：collect_stat=0 表示「我没收藏这条」，绝不入库（防点赞混入）
        cs = aw.get("collect_stat")
        if cs is not None:
            try:
                if int(cs) == 0:
                    continue
            except Exception:
                pass
        v = parse_aweme(aw)
        if not v:
            continue
        c = collects.setdefault(cid, {"name": "", "total": 0, "videos": {}})
        if v["id"] not in c["videos"]:
            c["videos"][v["id"]] = v
            added += 1
    return added


def on_response(resp):
    u = resp.url
    try:
        if "/aweme/v1/web/collects/list/" in u:
            j = resp.json()
            for it in (j.get("collects_list") or []):
                cid = str(it.get("collects_id") or "")
                if not cid:
                    continue
                c = collects.setdefault(cid, {"name": "", "total": 0, "videos": {}})
                if it.get("collects_name"):
                    c["name"] = it["collects_name"]
                c["total"] = max(c["total"], int(it.get("total_number") or 0))
        elif "/aweme/v1/web/collects/video/list/" in u:
            q = parse_qs(urlparse(u).query)
            cid = str((q.get("collects_id") or [""])[0])
            if cid:
                absorb(resp.json(), cid)
        elif "/aweme/v1/web/aweme/favorite/" in u:
            # ⚠ 这是【点赞/喜欢】列表，不是收藏！
            #    历史 bug：曾把它灌进 cid="0" 并命名为「默认收藏」，导致点赞视频混入
            #    知识库（2026-09-25、2026-10-07 两次被用户发现）。这里显式忽略。
            pass
        elif "/aweme/v1/web/aweme/listcollection/" in u:
            # 「全部收藏」扁平列表（真实收藏，按收藏时间倒序）。
            # 灌进哨兵 cid="0"，flush() 里再减去已归入命名夹的部分，
            # 得到的才是真正的「默认收藏」= 未归入任何收藏夹的散收藏。
            absorb(resp.json(), "0")
    except Exception:
        pass


def nice_page(page):
    page.goto(LIST_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(3500)
    try:
        t = page.get_by_text("收藏夹", exact=True).first
        if t.count() > 0 and t.is_visible():
            t.click()
            page.wait_for_timeout(2000)
    except Exception:
        pass


def wheel(page, n=1, dy=2800, pause=0.9):
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


def count_of(cid):
    return len(collects.get(cid, {}).get("videos", {}))


def merge_video(old, new):
    """用新抓到的记录覆盖同 id 旧记录（新记录带 play_urls 直链），但保留已处理字段"""
    if isinstance(old, dict):
        for k in KEEP:
            if k in old:
                new.setdefault(k, old[k])
    return new


def main():
    global SCROLL_IDLE, MAX_OCC, SCROLL_MAX_ONE
    plan_only = "--plan" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    deep = "--deep" in sys.argv
    union_only = "--union-only" in sys.argv
    only_names = None
    if "--only-names" in sys.argv:
        only_names = [s for s in sys.argv[sys.argv.index("--only-names") + 1].split("|") if s]
    if deep:
        SCROLL_IDLE, MAX_OCC, SCROLL_MAX_ONE = 6, 3, 45
        log(f"==> deep 模式：SCROLL_IDLE={SCROLL_IDLE} MAX_OCC={MAX_OCC} SCROLL_MAX_ONE={SCROLL_MAX_ONE}")

    acquired = False
    if not plan_only:
        if not acquire("fetch_gap"):
            return
        acquired = True

    def done():
        if acquired:
            release()

    # ---- 上次数据（预置，只增不减） ----
    prev = {}
    if OUT.exists():
        prev = json.loads(OUT.read_text(encoding="utf-8"))
    keep, by_name, loose, prev_names = {}, {}, {}, []
    for f in prev.get("folders", []):
        nm = f.get("name") or ""
        prev_names.append(nm)
        vids = {}
        for v in f.get("videos", []):
            kv = {k: v[k] for k in KEEP if k in v}
            if kv:
                keep[v["id"]] = kv
            vids[v["id"]] = v
        if nm == "默认收藏":
            loose = dict(vids)
        else:
            by_name[nm] = {"total": f.get("total") or 0, "videos": vids}
    prev_total = sum(len(f.get("videos", [])) for f in prev.get("folders", []))
    log(f"==> 上次：{len(prev_names)} 夹 / {prev_total} 条（已预置，只增不减）")

    def flush(final=False):
        custom = {vid for s in by_name.values() for vid in s["videos"]}
        loose_out = {vid: v for vid, v in loose.items() if vid not in custom}

        folders = []
        for nm, s in by_name.items():
            folders.append({"id": nm, "name": nm, "total": s["total"] or None,
                            "video_count": len(s["videos"]), "videos": list(s["videos"].values())})
        if loose_out:
            folders.append({"id": "默认收藏", "name": "默认收藏", "total": None,
                            "video_count": len(loose_out), "videos": list(loose_out.values())})
        order = {n: i for i, n in enumerate(prev_names)}
        folders.sort(key=lambda f: order.get(f["name"], 10 ** 6))

        for f in folders:
            for v in f["videos"]:
                kv = keep.get(v["id"])
                if kv:
                    for k, val in kv.items():
                        v.setdefault(k, val)

        total = sum(len(f["videos"]) for f in folders)
        if prev_total and total < prev_total * 0.9:
            log(f"!! 结果骤降（{total} < {prev_total}*0.9），拒绝覆盖")
            (ROOT / "data" / "favorites.gap.draft.json").write_text(
                json.dumps({"total_videos": total, "folders": folders}, ensure_ascii=False, indent=1),
                encoding="utf-8")
            return None
        OUT.write_text(json.dumps({"fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                   "total_videos": total, "folders": folders},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"    .. 已落盘：{len(folders)} 夹 / {total} 条")
        return total

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE), headless=False, viewport={"width": 1380, "height": 900},
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", on_response)
        ck = {c["name"] for c in ctx.cookies()}
        log(f"==> 登录态 sessionid: {'有 OK' if 'sessionid' in ck else '无 FAIL'}")

        # A. 清单 + 每夹首页预览
        log("==> A. 收藏夹列表（清单 + 每夹首页预览）…")
        nice_page(page)
        wheel(page, SCROLL_LIST, 2500, 0.7)
        log(f"    清单：{len(collects)} 个夹 / 标注总数 {sum(c['total'] for c in collects.values())} 条")

        # A2. 全部收藏（扁平列表 listcollection）→ 用于算出「默认收藏 = 未归档散收藏」
        log("==> A2. 全部收藏（未归档散收藏的来源）…")
        page.goto(FAV_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3500)
        try:
            t = page.get_by_text("视频", exact=True).first
            if t.count() > 0 and t.is_visible():
                t.click()
                page.wait_for_timeout(2500)
        except Exception:
            pass
        last, idle = -1, 0
        for _ in range(200):
            wheel(page, 1, 3000, 1.2)
            now = count_of("0")
            if now == last:
                idle += 1
                if idle >= SCROLL_IDLE:
                    break
            else:
                idle, last = 0, now
        log(f"    全部收藏：{count_of('0')} 条")

        if union_only:
            for vid, v in collects.get("0", {}).get("videos", {}).items():
                loose[vid] = merge_video(loose.get(vid), v)
            ctx.close()
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            total = flush(final=True)
            log(f"==> 完成（union-only）：{total} 条")
            done()
            return

        todo = [(cid, c["name"], c["total"], count_of(cid))
                for cid, c in collects.items()
                if cid not in ("0", "") and c["name"] and c["total"] > count_of(cid)]
        todo.sort(key=lambda x: -(x[2] - x[3]))
        if only_names:
            todo = [t for t in todo if t[1] in only_names]
            log(f"    --only-names → 只处理 {[t[1] for t in todo]}")
        gap = sum(t - h for _, _, t, h in todo)
        log(f"\n==> 需点开翻页：{len(todo)} 个夹 / 缺口 {gap} 条")
        for cid, name, total, have in todo:
            log(f"    {name}  {have}/{total}  缺 {total - have}")

        if plan_only:
            ctx.close()
            done()
            return

        if limit:
            todo = todo[:limit]
            log(f"    --limit {limit} → 本轮补：{[t[1] for t in todo]}")

        for i, (cid, name, total, have) in enumerate(todo, 1):
            log(f"\n[{i}/{len(todo)}] {name}（{have}/{total}）")
            try:
                # 同名收藏夹可能有多个卡片：依次尝试第 1、2、3… 个，直到抓够 total
                tried = 0
                best = count_of(cid)
                while tried < MAX_OCC:
                    nice_page(page)
                    loc = page.get_by_text(name, exact=True)
                    # 滚动把同名卡片都加载出来
                    for _ in range(25):
                        if loc.count() > tried:
                            break
                        wheel(page, 1, 2000, 0.7)
                    if loc.count() <= tried:
                        if tried == 0:
                            log("    !! 找不到卡片，跳过")
                        break
                    try:
                        el = loc.nth(tried)
                        if not el.is_visible():
                            wheel(page, 1, 1800, 0.7)
                        el.click(timeout=5000)
                    except Exception as e:
                        log(f"    点第 {tried + 1} 个同名卡片失败：{e}")
                        break
                    page.wait_for_timeout(2500)
                    last, idle = count_of(cid), 0
                    for _ in range(SCROLL_MAX_ONE):
                        wheel(page, 1, 3000, 1.4)
                        now = count_of(cid)
                        if total and now >= total:
                            break
                        if now == last:
                            idle += 1
                            if idle >= SCROLL_IDLE:
                                break
                        else:
                            idle = 0
                        last = now
                    got = count_of(cid)
                    tried += 1
                    best = max(best, got)
                    log(f"    第 {tried} 个同名卡片 → {got}/{total}")
                    if total and got >= total:
                        break
                got = best
                log(f"    → {got}/{total} {'OK' if got >= total else f'仍缺 {total - got}'}")
            except Exception as e:
                log(f"    !! 失败：{e}")

            slot = by_name.setdefault(name, {"total": 0, "videos": {}})
            slot["total"] = max(slot["total"], total or 0)
            for vid, v in collects.get(cid, {}).get("videos", {}).items():
                old = slot["videos"].get(vid)
                if isinstance(old, dict):
                    for k in KEEP:
                        if k in old:
                            v.setdefault(k, old[k])
                slot["videos"][vid] = v
            for vid, v in collects.get("0", {}).get("videos", {}).items():
                loose[vid] = merge_video(loose.get(vid), v)
            flush()

        log("\n==> 收尾合并…")
        for cid, c in collects.items():
            if cid in ("0", "") or not c["name"]:
                continue
            slot = by_name.setdefault(c["name"], {"total": 0, "videos": {}})
            slot["total"] = max(slot["total"], c["total"])
            for vid, v in c["videos"].items():
                old = slot["videos"].get(vid)
                if isinstance(old, dict):
                    for k in KEEP:
                        if k in old:
                            v.setdefault(k, old[k])
                slot["videos"][vid] = v
        for vid, v in collects.get("0", {}).get("videos", {}).items():
            loose[vid] = merge_video(loose.get(vid), v)
        ctx.close()

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        (BACKUP_DIR / f"favorites.{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(
            OUT.read_text(encoding="utf-8"), encoding="utf-8")
    total = flush(final=True)
    log(f"==> 完成：{total} 条")
    done()


if __name__ == "__main__":
    main()
