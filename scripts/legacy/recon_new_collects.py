# -*- coding: utf-8 -*-
"""侦察：抓取「全部收藏」列表并回答两个问题
  Q1 接口里到底有没有「收藏时间」字段？（如有，可精确回答「前几天新增」并修正排序口径）
  Q2 相对 10-07 基线（data/seen_ids.json）真正新增了哪些收藏？

产物：
  data/_probe_listcollection_raw.json  原始 aweme 数组 + 抓到的响应头（供离线复核）
  data/_recon_new.json                 {baseline, captured, new_ids:[{id,title,author,duration}]}
用法：python recon_new_collects.py
"""
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "browser_profile"
DATA = ROOT / "data"
FAV_URL = "https://www.douyin.com/user/self?showTab=favorite_collection"

sys.path.insert(0, str(ROOT / "scripts"))
from fetch_favorites import parse_aweme  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

awemes = {}          # aweme_id -> (order_index, raw aweme)
order = []
resp_meta = []
TIME_KEY = re.compile(r"(time|date|ts|stamp)", re.I)


def on_response(resp):
    u = resp.url
    if "/aweme/v1/web/aweme/listcollection/" not in u:
        return
    try:
        j = resp.json()
    except Exception:
        return
    q = parse_qs(urlparse(u).query)
    resp_meta.append({"url": u.split("?")[0],
                      "cursor": (q.get("cursor") or [""])[0],
                      "count": (q.get("count") or [""])[0],
                      "keys": list(j.keys()),
                      "has_more": j.get("has_more"),
                      "total": j.get("total")})
    for a in (j.get("aweme_list") or []):
        vid = str(a.get("aweme_id") or "")
        if vid and vid not in awemes:
            awemes[vid] = a
            order.append(vid)


def log(m):
    print(m, flush=True)


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        str(PROFILE), headless=False, viewport={"width": 1380, "height": 900},
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)
    log("==> 打开「全部收藏」…")
    page.goto(FAV_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    try:
        t = page.get_by_text("视频", exact=True).first
        if t.count() > 0 and t.is_visible():
            t.click()
            page.wait_for_timeout(2500)
            log("    已切到「视频」子标签")
    except Exception as e:
        log(f"    切子标签失败：{e}")

    last, idle = -1, 0
    for i in range(220):
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.mouse.move(690, 500)
            page.mouse.wheel(0, 3000)
        except Exception:
            pass
        page.wait_for_timeout(1200)
        now = len(awemes)
        if now == last:
            idle += 1
            if idle >= 4:
                break
        else:
            idle, last = 0, now
        if i % 20 == 0 and i:
            log(f"    …{now} 条")
    log(f"==> 捕获 {len(awemes)} 条全部收藏（响应 {len(resp_meta)} 个分页）")
    ctx.close()

# ---------- Q1：有没有收藏时间字段？ ----------
sample = next(iter(awemes.values())) if awemes else {}
hits = sorted(k for k in sample.keys() if TIME_KEY.search(k))
log("\n== Q1 时间相关字段 ==")
for k in hits:
    log(f"    {k} = {sample.get(k)!r}")
log(f"    —— 顶层键共 {len(sample)} 个；含 time/date 的 {len(hits)} 个")
# 再深挖一层：所有值是可秒级时间戳的字段
def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o[:3]):
            yield from walk(v, f"{path}[{i}]")
    else:
        yield path, o

ts_like = []
for path, v in walk(sample):
    if isinstance(v, int) and 1_500_000_000 < v < 2_000_000_000:
        ts_like.append((path, v, time.strftime("%Y-%m-%d %H:%M", time.localtime(v))))
log("\n== Q1b 所有『像是秒级时间戳』的字段 ==")
for path, v, human in ts_like[:25]:
    log(f"    {path} = {v}  → {human}")
if not ts_like:
    log("    （无）")

# ---------- Q2：相对基线新增了哪些 ----------
seen = set(json.loads((DATA / "seen_ids.json").read_text(encoding="utf-8")))
new_ids = [i for i in order if i not in seen]
log(f"\n== Q2 新增 ==")
log(f"    基线 seen_ids：{len(seen)} 条")
log(f"    本次捕获：{len(awemes)} 条")
log(f"    真正新增：{len(new_ids)} 条")
rows = []
for i in new_ids:
    a = awemes[i]
    v = parse_aweme(a) or {}
    rows.append({"id": i, "title": v.get("title", ""), "author": v.get("author", ""),
                 "duration": v.get("duration", ""), "url": v.get("url", ""),
                 "order": order.index(i)})
    log(f"    [{order.index(i):>3}] {v.get('duration','?'):>6}  {v.get('author','')[:14]:<14} {v.get('title','')[:52]}")

(DATA / "_probe_listcollection_raw.json").write_text(
    json.dumps({"captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "responses": resp_meta, "order": order,
                "awemes": awemes}, ensure_ascii=False), encoding="utf-8")
(DATA / "_recon_new.json").write_text(
    json.dumps({"baseline": len(seen), "captured": len(awemes),
                "new_ids": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
log(f"\n已写 → data/_probe_listcollection_raw.json / data/_recon_new.json")
