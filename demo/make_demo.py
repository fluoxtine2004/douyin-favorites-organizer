# -*- coding: utf-8 -*-
"""生成脱敏演示数据 + demo/index.html（不依赖抖音、不依赖 whisper）。

跑法：python demo/make_demo.py
产物：demo/index.html + demo/media/<id>/*.jpg
用途：让 clone 仓库的人立刻看到完整 UI（列表 / 详情时间轴 / 周报 / 待办），
      而无需登录抖音或下载模型。
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
MEDIA = DEMO / "media"
TPL = ROOT / "templates" / "dashboard.html"

MAJORS = ["学习", "生活", "成长", "旅游", "美食", "待归类"]

# ---- 12 条完全虚构的示例视频（人物/标题均为占位，非真实内容）----
VIDEOS = [
    ("9000000000000000001", "用 MCP 让本地文件夹变成 AI 的长期记忆", "学习", "AI工具", "MCP与Skills", "11:20", "示例作者A"),
    ("9000000000000000002", "三个月从零跑通一个副业小项目", "成长", "理财投资", "副业搞钱", "6:45", "示例作者B"),
    ("9000000000000000003", "考研复试：联系导师邮件的写法拆解", "学习", "科研", "论文写作", "4:12", "示例作者C"),
    ("9000000000000000004", "海边小城三天两晚的省钱路线", "旅游", "国内游", "海岛", "8:03", "示例作者D"),
    ("9000000000000000005", "十分钟搞定的高蛋白早餐", "美食", "早餐", "快手菜", "3:30", "示例作者E"),
    ("9000000000000000006", "为什么你总是坚持不下去：把目标切成 5 分钟", "成长", "认知成长", "心态建设", "7:18", "示例作者F"),
    ("9000000000000000007", "Obsidian 双链笔记的三种用法", "学习", "AI工具", "知识库工具", "9:47", "示例作者G"),
    ("9000000000000000008", "出租屋改造：500 元预算的桌面升级", "生活", "居家", "改造", "5:26", "示例作者H"),
    ("9000000000000000009", "一个人旅行的安全问题清单", "旅游", "出行准备", "安全", "6:02", "示例作者I"),
    ("9000000000000000010", "基金定投的常见误区和正确姿势", "成长", "理财投资", "资产配置", "12:35", "示例作者J"),
    ("9000000000000000011", "肩颈放松的五个动作（久坐人群）", "生活", "运动健身", "拉伸", "4:48", "示例作者K"),
    ("9000000000000000012", "一周备菜：周日两小时解决五天晚饭", "美食", "备餐", "meal prep", "10:09", "示例作者L"),
]

FAKE_SEGMENTS = [
    "先说明一个前提：这套方法我自己用了大概三个月，确实有效。",
    "第一步是把要解决的问题写清楚，写不清楚的地方往往就是卡点。",
    "第二步是找一个最小的可验证动作，今天就能做完的那种。",
    "第三步是记录结果，不记录就等于没做过，三天后你会忘记细节。",
    "这里要提醒一个常见的坑：一开始就想做完整方案，结果三天就放弃。",
    "最后总结一下，核心就一句话——把大目标切成今天能完成的小动作。",
]

FAKE_POINTS = [
    "把要解决的问题写清楚，写不清楚的地方往往就是卡点。",
    "找一个今天就能做完的最小可验证动作，先跑起来再优化。",
    "记录结果，否则三天后你就忘了当时的细节和判断。",
]

WEEKLY_TEXT = """**Week 2026-W42 · 本期整理小结**（示例数据，用于展示周报形态）

> 口径：对比上周基线，本期新增 **4 条**收藏，0 条消失；示例库共 **12 条**。

## 本期新增

- **用 MCP 让本地文件夹变成 AI 的长期记忆** → 学习 · AI工具。把「AI 每次都要重新认识你」变成「AI 认识你的文件夹」，本地优先、不用上传。(11:20)
- **为什么你总是坚持不下去：把目标切成 5 分钟** → 成长 · 认知成长。关键不是意志力，而是把启动成本降到「不拒绝」的程度。(7:18)
- **Obsidian 双链笔记的三种用法** → 学习 · 知识库工具。三种用法分别解决「找得到」「想得起」「连得上」。(9:47)

## 本周整体回顾

- **主题流向**：AI 工具（MCP、本地记忆）、个人知识管理（双链笔记）、行为设计（微习惯）。
- **值得回看**：⭐重要 2 条，🔔加入下期回顾 1 条。
- **可执行动作**：从「把目标切成 5 分钟」里取出 1 条，落到今天的待办里。

---
*示例数据由 `demo/make_demo.py` 生成；真机上这里是每周自动产出的整理小结，季度 / 年度会再往上聚合。*
"""


def make_image(path: Path, title: str, sub: str, hue: int):
    """自绘截图：渐变底 + 标题 + 时间码（模拟视频画面）。"""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    W, H = 960, 540
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    # 渐变
    for y in range(H):
        p = y / H
        r = int(30 + 60 * p + 20 * math.sin(hue / 40))
        g = int(40 + 70 * (1 - p))
        b = int(90 + 80 * p)
        d.line([(0, y), (W, y)], fill=(r % 200, g % 200, b % 220))
    d.rectangle([0, H - 96, W, H], fill=(0, 0, 0))
    d.text((36, H - 78), sub, fill=(255, 255, 255))
    # 标题换行
    line, y0 = "", 150
    for ch in title:
        line += ch
        if len(line) >= 14:
            d.text((40, y0), line, fill=(255, 255, 255))
            y0 += 54
            line = ""
    if line:
        d.text((40, y0), line, fill=(255, 255, 255))
    d.text((40, 60), "DEMO · 示例画面", fill=(200, 220, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, quality=82)
    return True


def build():
    MEDIA.mkdir(parents=True, exist_ok=True)
    data, new_ids = [], []
    for i, (vid, title, major, lv2, lv3, dur, author) in enumerate(VIDEOS):
        ts = 1760000000 + i * 86400
        frames = []
        for k in range(3):
            t = 20 + k * 45
            rel = f"media/{vid}/kf_{t:05d}.jpg"
            ok = make_image(DEMO / rel, f"{title}", f"示例画面 {k + 1}/3 · {t // 60}:{t % 60:02d}", hue=i * 30 + k * 60)
            frames.append({"url": rel if ok else "", "t": t, "cap": f"{t // 60}:{t % 60:02d}"})
        cover = f"media/{vid}/cover.jpg"
        make_image(DEMO / cover, title, "封面 · 示例", hue=i * 30)
        segs = [{"t": j * 12, "text": FAKE_SEGMENTS[(i + j) % len(FAKE_SEGMENTS)]}
                for j in range(len(FAKE_SEGMENTS))]
        data.append({
            "id": vid, "title": title, "full_title": title + " #示例标签 #demo",
            "url": f"https://www.douyin.com/video/{vid}",
            "cover": cover, "author": author, "duration": dur,
            "ts": ts, "date": "2026-09-20",
            "cb": 9 - (i // 4), "ci": i, "cdate": "2026-10-12", "cbefore": "",
            "captured": "2026-10-12 12:00:00",
            "folder": "示例收藏夹" + str(i % 3 + 1),
            "major": major, "auto_major": major, "lv2": lv2, "lv3": lv3, "tags": [lv2, lv3],
            "summary": f"（示例）这条视频讲了「{title}」，演示用的一句话总结会出现在列表卡片上。",
            "points": FAKE_POINTS, "segments": segs, "frames": frames,
            "has_transcript": True, "no_transcript": False,
        })
        if i >= 9:
            new_ids.append(vid)

    taxo = {
        "学习": {"AI工具": ["MCP与Skills", "Vibe Coding", "知识库工具"], "科研": ["论文写作", "文献阅读"]},
        "成长": {"理财投资": ["资产配置", "副业搞钱"], "认知成长": ["心态建设", "复盘方法"]},
        "生活": {"运动健身": ["拉伸"], "居家": ["改造"]},
        "旅游": {"国内游": ["海岛"], "出行准备": ["安全"]},
        "美食": {"早餐": ["快手菜"], "备餐": ["meal prep"]},
        "待归类": {},
    }
    daily_cases = {"cases": [
        {"title": "给收藏夹做一次「最小整理」", "major": "学习",
         "action": "打开自己的收藏夹，只挑最近 10 条，给每条写一句话：这条视频解决什么问题。",
         "why": "演示页的「每日推荐」会从这里取；写一句话是把收藏变成知识的最小动作。"},
        {"title": "把一条长视频变成可检索的笔记", "major": "成长",
         "action": "找一条 30 分钟以上的视频，只记 3 个要点和对应的时间点。",
         "why": "时间点是回看视频的唯一索引，没有时间点的笔记等于没记。"},
    ]}

    html = TPL.read_text(encoding="utf-8")
    repl = {
        "__DATA__": json.dumps(data, ensure_ascii=False),
        "__MAJORS__": json.dumps(MAJORS, ensure_ascii=False),
        "__TAXO__": json.dumps(taxo, ensure_ascii=False),
        "__FOLDERS__": json.dumps(sorted({d["folder"] for d in data}), ensure_ascii=False),
        "__DAILY_CASES__": json.dumps(daily_cases, ensure_ascii=False),
        "__WEEKLY__": json.dumps({"text": WEEKLY_TEXT, "label": "3 个收藏夹"}, ensure_ascii=False),
        "__OVERRIDES__": json.dumps({}, ensure_ascii=False),
        "__NEW_IDS__": json.dumps(new_ids, ensure_ascii=False),
    }
    for k, v in repl.items():
        html = html.replace(k, v)
    left = [k for k in repl if k in html]
    (DEMO / "index.html").write_text(html, encoding="utf-8")
    print(f"✅ demo/index.html 已生成（{len(data)} 条示例，未替换占位符: {left or '无'}）")
    print(f"   截图目录: {MEDIA}")


if __name__ == "__main__":
    build()
