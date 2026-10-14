# -*- coding: utf-8 -*-
"""实验 2：用真实手势/键盘驱动滚动容器，看哪种能触发加载更多"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "browser_profile"
FAV_URL = "https://www.douyin.com/user/self?showTab=favorite_collection"

ids, seen = [], set()


def on_response(resp):
    if "/aweme/v1/web/aweme/favorite/" in resp.url:
        try:
            for a in (resp.json().get("aweme_list") or []):
                v = str(a.get("aweme_id") or "")
                if v and v not in seen:
                    seen.add(v)
                    ids.append(v)
        except Exception:
            pass


BOX = """() => {
  let best=null, bestD=0;
  document.querySelectorAll('div').forEach(el => {
    const d = el.scrollHeight - el.clientHeight;
    if (d > bestD && el.clientHeight > 300) { bestD=d; best=el; }
  });
  if (!best) return null;
  const r = best.getBoundingClientRect();
  return {x: r.x + r.width/2, y: r.y + r.height/2, scrollH: best.scrollHeight, clientH: best.clientHeight};
}"""

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=True,
                                               viewport={"width": 1380, "height": 900})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)
    page.goto(FAV_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(7000)
    bx = page.evaluate(BOX)
    print("容器:", bx, "| 初始条数:", len(ids))

    def report(tag, rnd):
        print(f"  [{tag}] 轮 {rnd}: {len(ids)} 条", flush=True)

    # 策略 1：鼠标移到容器中心 + 真实滚轮
    print("\n== 策略1：鼠标悬停容器 + mouse.wheel ==")
    for r in range(10):
        page.mouse.move(bx["x"], bx["y"])
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(1500)
        report("wheel", r + 1)
        if len(ids) > 20:
            break

    # 策略 2：拖拽滚动条
    if len(ids) == 20:
        print("\n== 策略2：拖动滚动条 ==")
        for r in range(10):
            try:
                page.mouse.move(bx["x"] + 400, bx["y"] - 300)
                page.mouse.down()
                page.mouse.move(bx["x"] + 400, bx["y"] - 100, steps=12)
                page.mouse.up()
            except Exception:
                pass
            page.wait_for_timeout(1500)
            report("drag", r + 1)
            if len(ids) > 20:
                break

    # 策略 3：键盘
    if len(ids) == 20:
        print("\n== 策略3：键盘 End / PageDown ==")
        try:
            page.mouse.click(bx["x"], bx["y"])
            page.wait_for_timeout(600)
        except Exception:
            pass
        for r in range(20):
            page.keyboard.press("End")
            page.wait_for_timeout(400)
            page.keyboard.press("PageDown")
            page.wait_for_timeout(1200)
            report("key", r + 1)
            if len(ids) > 20:
                break

    # 策略 4：找到内部真正滚动的元素（含 class 匹配）
    if len(ids) == 20:
        print("\n== 策略4：逐个候选容器滚到底 ==")
        n = page.evaluate("""() => {
          const els = [];
          document.querySelectorAll('div').forEach(el => {
            if (el.scrollHeight - el.clientHeight > 200 && el.clientHeight > 200) els.push(el);
          });
          els.sort((a,b)=>(b.scrollHeight-b.clientHeight)-(a.scrollHeight-a.clientHeight));
          els.forEach(e => { e.scrollTop = e.scrollHeight - e.clientHeight; e.dispatchEvent(new Event('scroll',{bubbles:true})); });
          return els.length;
        }""")
        for r in range(15):
            page.mouse.move(bx["x"], bx["y"])
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(1300)
            report(f"multi({n})", r + 1)
            if len(ids) > 20:
                break

    (ROOT / "data" / "_probe_order_test.json").write_text(
        json.dumps({"ids": ids}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n最终条数:", len(ids), "→ data/_probe_order_test.json")
    ctx.close()
