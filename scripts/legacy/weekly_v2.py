# -*- coding: utf-8 -*-
"""
周报 v2：按「学习 / 执行 / 了解 / 可运行」四栏组织
  - 学习   博主教的知识、方法、教程（值得内化的内容）
  - 执行   博主明确布置的作业/行动/习惯（可直接照做，列成清单）
  - 了解   行业/资讯/视野类（知道即可，不必投入）
  - 可运行 含明确工具/软件/AI 方案（如 Claude/Cursor/AI skill 等），需先核实可行性、经用户同意后运行

用法：python weekly_v2.py [--week-label "首次全量"] [--top 6]
"""
import argparse
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAV = ROOT / "data" / "favorites.json"
ENR = ROOT / "data" / "enriched.json"
OUT = ROOT / "vault" / "00-周报"

# ---------- 精确分类信号 ----------
# 1) 可运行：必须出现具体工具/产品名（白名单，避免误命中）
RUNNABLE_TOOLS = [
    "claude", "chatgpt", "gpt-", "gemini", "cursor", "codex", "vibe coding", "vibecoding",
    "obsidian", "notion", "github", "copilot", "midjourney", "stable diffusion", "sd 绘画",
    "ai skill", "aiskill", "skill", "python", "mcp", "agent", "工作流", "workflow",
    "自动化", "脚本", "部署", "插件", "提示词", "prompt", "templates", "模板",
]
# 2) 执行：博主明确布置动作/作业/习惯/挑战（有明确指令语义）
TASK_PHRASES = [
    "作业", "任务", "行动清单", "试试", "挑战", "打卡", "坚持", "跟着做", "一起做",
    "动手", "复现", "实践", "30天", "21天", "每天", "按我说的做", "按我做的", "照着做",
    "计划表", "自检", "复盘", "去执行", "现在就", "趁热", "推荐你去",
]
# 3) 了解：视野/资讯/杂谈/认知/观影
AWARE_PHRASES = [
    "视野", "资讯", "新闻", "行业趋势", "观点", "杂谈", "漫谈", "解读", "观察",
    "世界", "人生意义", "感悟", "电影", "影评", "vlog", "旅行", "记录",
]
# 4) 学习：教程/方法/经验/干货类（默认兜底也是学习）

# 收藏夹 → 大类映射（与 categories.json 对齐）
MAJOR_MAP = {
    "研生活，应该做什么": "成长", "实习": "成长", "经验": "成长", "创业": "成长",
    "韭菜": "成长", "润": "成长", "jack": "成长", "梦想家": "成长", "梦生": "成长",
    "眼界需要做什么": "成长", "工作": "成长", "economy": "成长", "social": "成长",
    "business": "成长", "人生意义": "成长", "理想": "成长", "经验帖": "成长",
    "商": "成长", "思考": "成长", "坚持": "成长", "对世界看法": "成长",
    "ai": "学习", "GitHub": "学习", "科研": "学习", "obsidian": "学习", "ai创意": "学习",
    "毕业论文": "学习", "agent": "学习", "vibe Coding": "学习", "刺激学习": "学习",
    "研究生": "学习", "学习额外": "学习", "阅读记录法": "学习", "这才是保研": "学习",
    "考研经验": "学习", "伴学time": "学习",
    "workout": "生活", "part of me": "生活", "健身": "生活", "音乐": "生活",
    "funny game": "生活", "dirty": "生活", "锻炼": "生活", "想要的\u201cstrong\u201d生活": "生活",
    "小松 channel": "生活", "听": "生活", "影视集合": "生活", "影视": "生活",
    "居家思路": "生活", "缓解": "生活", "治愈": "生活", "画画": "生活", "要拍的": "生活",
    "感觉feel": "生活", "纯": "生活", "白噪音": "生活",
    "旅游目的地": "旅游", "徒步": "旅游", "旅游攻略": "旅游", "旅行的意义": "旅游",
    "美食": "美食",
}
DEFAULT_MAJOR = "待归类"


def safe(s, n=80):
    return re.sub(r"[\r\n]+", " ", str(s)).strip()[:n]


def major_of(folder):
    return MAJOR_MAP.get(folder, DEFAULT_MAJOR)


def has_kw(text, kws):
    t = text.lower()
    return [k for k in kws if k.lower() in t]


def classify(v, enr):
    """返回 (栏目, 命中的关键词)"""
    title = v.get("title") or ""
    text = title + " " + (enr.get("summary") or "") + " " + (v.get("transcript") or "")
    t = text.lower()
    # 可运行：必须命中具体工具白名单（优先级最高）
    run_hits = [k for k in RUNNABLE_TOOLS if k in t]
    if run_hits:
        return "可运行", run_hits
    # 执行：有明确动作指令
    task_hits = [k for k in TASK_PHRASES if k in t]
    if task_hits:
        return "执行", task_hits
    # 了解：视野/资讯/观影/旅行
    aware_hits = [k for k in AWARE_PHRASES if k in t]
    if aware_hits:
        return "了解", aware_hits
    return "学习", []


def build(week_label, top=6):
    fav = json.loads(FAV.read_text(encoding="utf-8"))
    enr = json.loads(ENR.read_text(encoding="utf-8"))
    vids = []
    for f in fav["folders"]:
        for v in f["videos"]:
            v["folder"] = f["name"]
            vids.append(v)

    buckets = {"学习": [], "执行": [], "了解": [], "可运行": []}
    for v in vids:
        e = enr.get(v["id"]) or {}
        cat, hits = classify(v, e)
        buckets[cat].append({
            "title": safe(v.get("title")),
            "author": v.get("author", ""),
            "folder": v.get("folder", ""),
            "url": v.get("url", ""),
            "major": major_of(v.get("folder", "")),
            "summary": safe(e.get("summary") or v.get("title") or "", 150),
            "points": (e.get("points") or [])[:3],
            "hits": hits,
        })

    today = date.today()
    yy, ww = today.isocalendar()[:2]
    # 「新增收藏」= 本期**真正新收藏**（new_ids.json），不是「本期整理了多少条」（坑位 R）：
    # 旧实现写 len(vids) → 周报头部显示「新增收藏: 1470」这种明显虚报。
    new_n, new_date = 0, ""
    try:
        _nj = json.loads((ROOT / "data" / "new_ids.json").read_text(encoding="utf-8"))
        new_n = len(_nj.get("ids") or [])
        new_date = _nj.get("date") or ""
    except Exception:
        pass
    if new_date and week_label in ("", "首次全量", "本周"):
        week_label = f"增量（{new_date}）"
    L = [
        "---",
        f'标题: "Week {yy}-W{ww} 抖音收藏周报"',
        f"周期: {week_label}",
        f"新增收藏: {new_n}（本期整理 {len(vids)} 条）",
        "---",
        "",
        f"# 📋 Week {yy}-W{ww} 周报（四栏版）",
        "",
        f"本期共 **{len(vids)}** 条收藏，按四栏整理：",
        "",
        "> 💡 **可运行** = 含明确工具/软件/AI 方案，我会先核实可行性，**经你同意后**再运行。",
        "> ✅ **执行** = 博主明确布置了可照做的动作，已列成清单。",
        "",
    ]
    # 一览
    L += ["## 一览", "", "| 栏目 | 条数 | 说明 |", "|---|---|---|"]
    desc = {
        "学习": "教程/方法/经验，值得内化",
        "执行": "博主布置的作业/行动/习惯",
        "了解": "视野/资讯/观影，知道即可",
        "可运行": "含工具/AI 方案，待你批准",
    }
    for k in ["学习", "执行", "了解", "可运行"]:
        L.append(f"| {k} | {len(buckets[k])} | {desc[k]} |")
    L.append("")

    # 执行栏：清单式（博主叫做的事，独立成 checklist）
    if buckets["执行"]:
        L += ["## ✅ 博主布置的行动清单（可直接照做）", ""]
        for it in buckets["执行"][:top]:
            L.append(f"- [ ] **{it['title']}**（{it['author']}，{it['major']}）")
            if it["summary"]:
                L.append(f"    {it['summary']}")
        L.append("")

    # 可运行栏：待批准方案（最醒目，放前面）
    if buckets["可运行"]:
        L += ["## 🚀 可运行方案（待你批准）", "",
              "> 以下条目含工具/教程/AI 方案，我会逐条核实可行性后**等你确认**再运行：", ""]
        for it in buckets["可运行"][:top]:
            L.append(f"### {it['title']}")
            meta = f"作者 {it['author']} ｜ 大类 {it['major']} ｜ 收藏夹 {it['folder']}"
            L.append(f"*{meta}*")
            L.append("")
            if it["summary"]:
                L.append(it["summary"])
            L.append("")
            L.append(f"[▶ 原视频]({it['url']})")
            L.append("")

    # 学习栏
    if buckets["学习"]:
        L += ["## 📚 学习（教程/方法/经验）", ""]
        for it in buckets["学习"][:top]:
            L.append(f"### {it['title']}")
            L.append(f"*作者 {it['author']} ｜ 大类 {it['major']}*")
            L.append("")
            if it["summary"]:
                L.append(it["summary"])
            L.append("")
            L.append(f"[▶ 原视频]({it['url']})")
            L.append("")

    # 了解栏
    if buckets["了解"]:
        L += ["## 👀 了解（视野/资讯/观影）", ""]
        for it in buckets["了解"][:top]:
            L.append(f"- **{it['title']}**（{it['author']}，{it['major']}）— {it['summary']}")
        L.append("")

    L += ["", "## ✍️ 本周批注汇总", "", "（你在网页/Obsidian 里写的批注会自动汇总到这里）", ""]
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--week-label", default="本周")
    ap.add_argument("--top", type=int, default=6)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    md = build(a.week_label, a.top)
    out = Path(a.out) if a.out else (OUT / f"Week {date.today().isocalendar()[0]}-W{date.today().isocalendar()[1]}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"✅ 周报 v2 已生成：{out}")
