# -*- coding: utf-8 -*-
"""
专题整理：按关键词把收藏内容归入主题笔记（vault/专题/*.md）
用法：python build_topics.py

★ 这个文件就是给你自己改的地方 —— 见下面 TOPICS 的注释。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "vault" / "专题"

# ============================================================================
# 专题配置（★ 改成你自己的）
# ----------------------------------------------------------------------------
# 每个专题有两种归集方式，二选一：
#   · keywords   —— 按关键词自动归集，省事，推荐先用这个
#                   会在「视频标题 + AI 总结」里做正则匹配
#   · groups     —— 手动指定视频 id 并分组（精细，但 id 得自己填）
#                   id 就是收藏那条视频的 aweme_id（19 位数字），
#                   可从 data/favorites.json 里找，或从网页详情页 URL 里拿
#
# 可选字段：
#   scope_folder —— 只在某个收藏夹内找（值填收藏夹名，如 "ai" 或 "默认收藏"）；
#                   不填 = 全库搜
#   tips         —— 生成的笔记末尾附一段「建议的阅读顺序」
# ============================================================================
TOPICS = [
    {
        "file": "AI与效率工具.md",
        "title": "AI / 效率工具 专题",
        "desc": "把收藏里 AI、编程、生产力工具相关的内容按关键词自动归集。",
        "scope_folder": None,
        "keywords": r"(ai|gpt|claude|agent|prompt|编程|代码|效率|工具|obsidian|notion|自动化)",
        "groups": [],
        "tips": [
            "先看「概念 / 入门」类建立整体地图，再挑一个工具往深里用",
            "别见一个装一个：先想清楚要解决什么问题，再决定用哪个工具",
        ],
    },
    {
        "file": "学习与成长.md",
        "title": "学习 / 成长 专题",
        # ↓ 想手动编排顺序时这样写（id 换成你自己的）：
        # "groups": [
        #     ("一、先搞懂概念", ["<视频id1>", "<视频id2>"]),
        #     ("二、动手实践",   ["<视频id3>"]),
        # ],
        "desc": "按关键词归集学习方法、读书、认知相关的内容。",
        "scope_folder": None,
        "keywords": r"(学习|读书|笔记|方法|认知|思维|记忆|效率|自律|复盘)",
        "groups": [],
        "tips": [
            "按「输入 → 整理 → 输出」三段来看，缺哪段补哪段",
        ],
    },
    {
        "file": "求职与实习.md",
        "title": "求职 / 实习 / 面试 专题",
        "desc": "按关键词归集简历、面试、谈薪、实习、求职相关的内容。",
        "scope_folder": None,
        "keywords": r"(实习|求职|面试|简历|offer|秋招|春招|校招|谈薪|转行|就业|招聘|职场|hr|大厂)",
        "groups": [],
        "tips": [
            "先看「面试与谈薪」建立底线，再看「怎么找渠道」补齐信息源",
        ],
    },
    {
        "file": "理财与投资.md",
        "title": "理财 / 投资 专题",
        "desc": "按关键词归集理财、投资、副业相关的内容。",
        "scope_folder": None,
        "keywords": r"(理财|投资|基金|股票|股息|红利|资产|记账|储蓄|保险|副业|搞钱)",
        "groups": [],
        "tips": [
            "先建立「现金流 / 风险」的概念，再碰具体品种",
            "警惕高收益承诺：任何测算表都自己复算一遍",
        ],
    },
]


def load():
    d = json.loads((ROOT / "data" / "favorites.json").read_text(encoding="utf-8"))
    e = json.loads((ROOT / "data" / "enriched.json").read_text(encoding="utf-8"))
    n = json.loads((ROOT / "data" / "llm_notes.json").read_text(encoding="utf-8"))
    return d, e, n


def brief(v, e, n):
    note = n.get(v["id"], {}) or {}
    en = e.get(v["id"], {}) or {}
    s = note.get("summary") or en.get("summary") or ""
    t = (v.get("title") or "").replace("\n", " ").strip()
    t = t if len(t) <= 46 else t[:46] + "…"
    dur = v.get("duration") or ""
    dtxt = f"（{dur}）" if dur and dur != "0:00" else ""
    return t, dtxt, s, v.get("url", "")


def main():
    data, enr, notes = load()
    all_vids = {}
    for f in data.get("folders", []):
        for v in f.get("videos", []):
            v["_folder"] = f.get("name", "")
            all_vids.setdefault(v["id"], v)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    made = []
    for t in TOPICS:
        pool = list(all_vids.values())
        if t.get("scope_folder"):
            pool = [v for v in pool if v.get("_folder") == t["scope_folder"]]
        if t.get("keywords"):
            rx = re.compile(t["keywords"], re.I)
            pool = [v for v in pool if rx.search((v.get("title") or "") + " " + ((notes.get(v["id"]) or {}).get("summary") or ""))]
        L = ["---", f'标题: "{t["title"]}"', "tags: [抖音收藏, 专题]", "---", "",
             f'# {t["title"]}', "", f'> {t["desc"]}', f'> 本期共 {len(pool)} 条。', ""]
        for name, ids in t.get("groups", []):
            L.append(f"## {name}\n")
            for vid in ids:
                v = all_vids.get(vid)
                if not v:
                    continue
                tt, dtxt, s, url = brief(v, enr, notes)
                L.append(f"- **{tt}**{dtxt}\n  {s}\n  [原视频]({url})")
            L.append("")
        if not t.get("groups"):
            L.append("## 内容清单\n")
            for v in pool:
                tt, dtxt, s, url = brief(v, enr, notes)
                L.append(f"- **{tt}**{dtxt}（📁 {v.get('_folder','')}）\n  {s}\n  [原视频]({url})")
            L.append("")
        if t.get("tips"):
            L.append("## 建议的阅读顺序\n")
            for i, x in enumerate(t["tips"], 1):
                L.append(f"{i}. {x}")
            L.append("")
        L.append("---\n")
        L.append("_由「抖音收藏知识库」自动生成；在网页里改分类并导出 overrides.json 后重建即可生效。_")
        p = OUT_DIR / t["file"]
        p.write_text("\n".join(L), encoding="utf-8")
        made.append((t["title"], len(pool), p))
    for title, cnt, p in made:
        print(f"✅ {title}：{cnt} 条 → {p}")


if __name__ == "__main__":
    main()
