# -*- coding: utf-8 -*-
"""
自动分级：给每条视频分配 一级(大类) / 二级 / 三级，写入 data/auto_taxonomy.json
优先级（构建时）：用户 overrides.json > 本文件自动分级 > 收藏夹映射
用法：python auto_taxonomy.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---------- 一级（大类）：沿用 categories.json 的夹映射 + video_major.json ----------
def load_major_funcs():
    cfg = json.loads((ROOT / "config" / "categories.json").read_text(encoding="utf-8"))
    mapping, rules = cfg.get("mapping", {}), cfg.get("rules", {})
    vmaj = {}
    vp = ROOT / "data" / "video_major.json"
    if vp.exists():
        try:
            vmaj = json.loads(vp.read_text(encoding="utf-8")).get("map", {})
        except Exception:
            vmaj = {}

    def folder_major(name: str) -> str:
        if name in mapping:
            return mapping[name]
        for mj, kws in rules.items():
            if any(k.lower() in (name or "").lower() for k in kws):
                return mj
        return "待归类"

    return vmaj, folder_major


# ---------- 二级/三级 规则表 ----------
# 每条：(二级名, 匹配正则, 三级规则[(三级名, 正则)])
RULES = {
    "成长": [
        ("求职实习", r"实习|求职|面试|简历|offer|秋招|春招|校招|谈薪|招聘|大厂|就业|职场|转行|工作|mentor|应届|背调",
         [("面试", r"面试|口试|二面|三面|群面"), ("简历", r"简历|resume|cv"),
          ("谈薪", r"谈薪|薪资|定级|ssp|白菜价|待遇"), ("实习选择", r"实习|mentor|带教|转正")]),
        ("理财投资", r"理财|投资|基金|股票|股息|红利|攒股|资产|搞钱|副业|创业|电商|外贸|期权|交易|套利|税务|赚钱|生意|店铺|摆摊|销售|变现|商业模式",
         [("资产配置", r"资产|配置|基金|股票|股息|红利|攒股|组合|定投"),
          ("副业搞钱", r"副业|创业|电商|外贸|摆摊|店铺|生意|变现|销售|平台"),
          ("消费观", r"消费|省钱|陷阱|花钱|买")]),
        ("认知成长", r"认知|思维|成长|读书|学习|心态|意义|复盘|习惯|自省|运气|选择|认识人|眼界|焦虑|内耗|拖延|专注|概率|直觉|人生|哲学|价值观|自律|情绪管理",
         [("读书", r"读书|看书|阅读|书单"), ("城市与选择", r"一线|城市|选择|出国|留学|路径"),
          ("心态建设", r"焦虑|内耗|心态|拖延|专注|自律|情绪|意义|运气"),
          ("复盘方法", r"复盘|记录|日记|数据化|习惯")]),
    ],
    "学习": [
        ("科研", r"科研|论文|文献|实验|导师|毕业设计|开题|查重|期刊|ssci|sci|答辩|学术|知网|维普|notebooklm|研究方法|综述",
         [("论文写作", r"论文|写作|查重|降重|格式|交叉引用|答辩|开题"),
          ("文献阅读", r"文献|综述|notebooklm|读文献"), ("科研工具", r"工具|软件|绘图|origin|zotero|codex|ai")]),
        ("AI工具", r"\bai\b|mcp|skill|agent|codex|claude|cursor|gemini|chatgpt|deepseek|prompt|obsidian|vibecoding|vibe coding|copilot|编程|大模型|智能体|自动化|工作流",
         [("MCP与Skills", r"mcp|skill|技能"), ("Vibe Coding", r"vibecoding|vibe coding|cursor|copilot|编程|开发"),
          ("模型与配置", r"claude|codex|gemini|chatgpt|deepseek|模型|api"), ("知识库工具", r"obsidian|notebooklm|知识库|笔记")]),
        ("英语", r"英语|口语|听力|翻译|雅思|托福|四六级|影子跟读",
         [("口语", r"口语|跟读|发音"), ("听力", r"听力|听写"), ("词汇语法", r"单词|语法|词汇")]),
    ],
    "生活": [
        ("运动健身", r"健身|训练|跑步|马拉松|攀岩|tabata|腹肌|运动|引体|workout|体态",
         [("跑步", r"跑步|马拉松"), ("攀岩", r"攀岩|抱石"), ("居家训练", r"tabata|腹肌|居家|跟练|体态")]),
        ("音乐", r"音乐|歌单|bgm|翻唱|现场|钢琴|小提琴|rnb|rap|歌曲|演奏",
         [("歌单", r"歌单|合集|推荐"), ("现场演出", r"现场|live|演唱会"), ("演奏", r"钢琴|小提琴|演奏|弹")]),
        ("情绪调节", r"助眠|白噪音|放松|疗愈|缓解|情绪|冥想|雨声|睡眠|调节|治愈|声音",
         [("助眠白噪音", r"助眠|白噪音|雨声|睡眠"), ("情绪疗愈", r"疗愈|治愈|缓解|情绪"), ("冥想调节", r"冥想|调节|身心")]),
        ("日常记录", r"日常|vlog|穿搭|ootd|皮套|直播|宿舍|居家|分享照片|记录",
         [("穿搭", r"穿搭|ootd"), ("生活记录", r"日常|vlog|记录|宿舍|居家")]),
    ],
    "旅游": [
        ("国内", r"上海|杭州|南京|成都|泸州|皖南|深圳|贵州|北京|香港|塔门|石澳|西湖|骑行|青旅|机场|拍机|航线|徒步",
         [("上海", r"上海"), ("杭州", r"杭州"), ("南京", r"南京"), ("成都", r"成都|泸州"),
          ("其他国内", r".")]),
        ("国外", r"日本|神户|北海道|札幌|纽约|美国|德国|韩国|澳洲|英国|欧洲|越南|泰国|环球|留学|出国|移民|海外",
         [("日本", r"日本|神户|北海道|札幌"), ("北美", r"纽约|美国|加州"), ("欧洲", r"德国|英国|欧洲"),
          ("其他海外", r".")]),
        ("攻略方法", r"攻略|路线|机位|性价比|vlog|旅行|旅游",
         [("路线攻略", r"攻略|路线|机位"), ("旅行记录", r"vlog|旅行|旅游")]),
    ],
    "美食": [
        ("探店", r"探店|推荐|好吃|小吃|餐厅|美食|店|吃", [("本地小店", r"小店|苍蝇馆|本地"), ("连锁品牌", r"连锁|麦当劳|星巴克")]),
        ("菜谱做法", r"做法|菜谱|教程|自制|厨房", [("家常菜", r"家常|快手"), ("烘焙甜品", r"烤|蛋糕|甜品|冰淇淋")]),
        ("美食文化", r"价格|成本|生意|文化|为什么", [("价格与商业", r"价格|成本|生意|为什么"), ("饮食文化", r"文化|历史")]),
    ],
}


def classify(major: str, text: str):
    """返回 (二级, 三级)；命中不到就落到该大类的最后一个兜底二级"""
    rules = RULES.get(major) or []
    for lv2, rx, lv3s in rules:
        if re.search(rx, text, re.I):
            lv3 = ""
            for name, r2 in lv3s:
                if r2 == "." or re.search(r2, text, re.I):
                    lv3 = name
                    break
            return lv2, lv3
    # 兜底：该一级下的第一个二级
    if rules:
        lv2 = rules[0][0]
        lv3 = ""
        for name, r2 in rules[0][2]:
            if r2 == ".":
                lv3 = name
                break
        return lv2, lv3
    return "", ""


def main():
    data = json.loads((ROOT / "data" / "favorites.json").read_text(encoding="utf-8"))
    notes = json.loads((ROOT / "data" / "llm_notes.json").read_text(encoding="utf-8"))
    ovr = {}
    op = ROOT / "data" / "overrides.json"
    if op.exists():
        try:
            ovr = {k: v for k, v in json.loads(op.read_text(encoding="utf-8")).items() if not k.startswith("_")}
        except Exception:
            ovr = {}
    # 排除名单不参与统计
    excluded = set()
    xp = ROOT / "data" / "excluded.json"
    if xp.exists():
        try:
            excluded = set(json.loads(xp.read_text(encoding="utf-8")).get("ids", []))
        except Exception:
            excluded = set()
    vmaj, folder_major = load_major_funcs()

    out, dist = {}, {}
    for f in data.get("folders", []):
        for v in f.get("videos", []):
            vid = v["id"]
            if vid in excluded:
                continue
            o = ovr.get(vid) or {}
            major = o.get("major") or vmaj.get(vid) or folder_major(f.get("name", ""))
            note = notes.get(vid) or {}
            text = " ".join([v.get("title") or "", note.get("summary") or "",
                             " ".join(note.get("points") or [])]).lower()
            lv2, lv3 = classify(major, text)
            out[vid] = {"major": major, "lv2": lv2, "lv3": lv3}
            dist.setdefault(major, {}).setdefault(lv2 or "(未分)", 0)
            dist[major][lv2 or "(未分)"] += 1

    (ROOT / "data" / "auto_taxonomy.json").write_text(
        json.dumps({"_说明": "自动分级结果（用户 overrides.json 优先于本文件）", "map": out},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    total = len(out)
    print(f"✅ 自动分级完成：{total} 条")
    for major, d in dist.items():
        s = sum(d.values())
        print(f"\n【{major}】共 {s} 条")
        for lv2, c in sorted(d.items(), key=lambda kv: -kv[1]):
            print(f"    └ {lv2}: {c}")
    nolv2 = sum(1 for v in out.values() if not v["lv2"])
    print(f"\n未分到二级的条目：{nolv2}")


if __name__ == "__main__":
    main()
