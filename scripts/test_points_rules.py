# -*- coding: utf-8 -*-
"""要点护栏 / 笔记定点刷新的规则测试 + 数据不变量校验（防回归）。

为什么需要：这两条规则是用户点名两次的回归点（点赞混入、要点变成整篇文章），
所以护栏必须是**纯函数 + 显式阈值 + 单测**，不能靠运行时判断或等用户再次发现。

规则（显式）：
  R1 单条要点 ≤ 90 字（POINT_HARD_MAX），超出截断加「…」
  R2 每条视频最多 3 条要点（POINT_MAX_N）
  R3 单个字符串 > 200 字（POINT_DROP_OVER）判定为「整篇文稿」脏数据 → 整条丢弃
  R4 make_points 无分段输入 → 返回空列表
  R5 refresh_points 只替换「## 🎯 AI 要点」段，逐字稿 / 截图 / 我的批注原样保留
  R6 专题笔记（vault/专题）与周报（vault/00-周报）不参与孤儿笔记清理

用法：python test_points_rules.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import enrich as E                      # noqa: E402
import generate_outputs as G            # noqa: E402

FAIL = []


def check(name, cond, extra=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  ' + extra) if extra else ''}")
    if not cond:
        FAIL.append(name)


# ---------------- R1 / R2 / R3：clean_points ----------------
print("R1-R3 clean_points 阈值")
pts = E.clean_points(["短句"] * 5)
check("R2 最多 3 条", len(pts) == 3, f"len={len(pts)}")

long90 = "甲" * 90
pts = E.clean_points([long90])
check("R1 恰好 90 字不截断", pts[0] == long90, f"len={len(pts[0])}")
check("R1 ≤90 字（含省略号 ≤91）", len(pts[0]) <= 91, f"len={len(pts[0])}")

pts = E.clean_points(["乙" * 500])
check("R3 500 字整段文稿被丢弃", pts == [], f"pts={pts}")

pts = E.clean_points(["丙" * 150])
check("R1 150 字 → 截断到 ≤91", pts and len(pts[0]) <= 91, f"len={len(pts[0]) if pts else None}")

check("R1 空输入 → 空列表", E.clean_points(None) == [] and E.clean_points([]) == [])
check("R1 纯空白项被过滤", E.clean_points(["   ", "\n"]) == [])

# ---------------- R4：make_points ----------------
print("R4 make_points")
check("R4 无分段 → []", E.make_points([]) == [])
segs = [{"t": i * 10, "text": f"第{i}个知识点包含数字{i}与关键结论{i}"} for i in range(1, 12)]
mp = E.make_points(segs)
check("R4 有分段 → 1~3 条", 1 <= len(mp) <= 3, f"len={len(mp)}")
check("R4 每条 ≤91 字", all(len(p) <= 91 for p in mp), f"max={max((len(p) for p in mp), default=0)}")
check("R4 唯一 → 去重后无重复", len(set(mp)) == len(mp))

# ---------------- R5：refresh_points 定点替换 ----------------
print("R5 refresh_points 只改要点段")
old = ("---\n标题: \"x\"\n---\n\n# x\n\n## 🎯 AI 要点\n\n1. " + "旧" * 400 +
       "\n\n## 📄 逐字稿\n\n> 逐字稿内容保持不动\n\n## ✍️ 我的批注\n\n> [!note] 我的批注\n> - 用户写的批注\n")
new = G.refresh_points(old, "1. 新要点一\n2. 新要点二")
check("R5 旧要点被替换", "旧" * 20 not in new and "新要点一" in new)
check("R5 逐字稿保留", "> 逐字稿内容保持不动" in new)
check("R5 我的批注保留", "> - 用户写的批注" in new)
check("R5 标题/正文保留", new.startswith("---\n标题:"))
check("R5 无要点段的笔记原样返回", G.refresh_points("没有要点段", "x") == "没有要点段")

# ---------------- R6：孤儿笔记清理范围 ----------------
print("R6 清理范围排除 专题 / 00-周报")
src = (ROOT / "scripts" / "generate_outputs.py").read_text(encoding="utf-8")
check("R6 跳过 00-周报", '"00-周报"' in src)
check("R6 跳过 专题", '"专题"' in src)

# ---------------- 全库不变量 ----------------
print("全库不变量（真实数据）")
enr = json.loads((ROOT / "data" / "enriched.json").read_text(encoding="utf-8"))
lens = [len(str(p)) for v in enr.values() for p in (v.get("points") or [])]
check("不变量 A：所有要点 ≤90 字", all(x <= 90 for x in lens), f"max={max(lens) if lens else 0}")
check("不变量 B：每视频 ≤3 条要点",
      all(len(v.get("points") or []) <= 3 for v in enr.values()))
check("不变量 C：enriched 无 >200 字的要点项",
      all(x <= 200 for x in lens))

fav = json.loads((ROOT / "data" / "favorites.json").read_text(encoding="utf-8"))
check("不变量 D：每个收藏夹都有名字（无空名夹）",
      all(f.get("name") for f in fav["folders"]))

# R7：点赞残留为 0（用清洗前的备份取回被剔除的点赞 id 做回归守卫）
import glob  # noqa: E402
backups = sorted(glob.glob(str(ROOT / "data" / "_backup" / "favorites.predigg-*.json")))
if backups:
    raw = json.loads(Path(backups[0]).read_text(encoding="utf-8"))
    digg = [v["id"] for f in raw["folders"] if f["name"] == "默认收藏" for v in f["videos"]]
    print(f"R7 点赞残留守卫（基准 {len(digg)} 条被剔除的点赞 id）")
    check("R7 基准非空（否则该守卫失效）", len(digg) > 0, f"len={len(digg)}")
    for label, p in (("dashboard.html", ROOT / "dashboard.html"),
                     ("dist/data.json", ROOT / "dist" / "data.json"),
                     ("favorites.json", ROOT / "data" / "favorites.json"),
                     ("enriched.json", ROOT / "data" / "enriched.json")):
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8")
        hit = sum(1 for i in digg if i in txt)
        check(f"R7 {label} 无点赞 id", hit == 0, f"hit={hit}")
    vhit = 0
    for md in (ROOT / "vault").rglob("*.md"):
        t = md.read_text(encoding="utf-8")
        if any(f"/video/{i}" in t for i in digg):
            vhit += 1
    check("R7 vault 无点赞笔记", vhit == 0, f"hit={vhit}")
else:
    check("R7 备份存在（用于取回点赞基准）", False, "未找到 favorites.predigg-*.json")

# ---------------- R8：三处实现必须一致（单一规则，不得各写各的） ----------------
print("R8 clean_points 三处实现一致性")
import build_dashboard as B             # noqa: E402

battery = [
    None, [], ["  "], ["正常要点一句话"],
    ["甲" * 90], ["乙" * 91], ["丙" * 150], ["丁" * 200], ["戊" * 201], ["己" * 500],
    ["一", "二", "三", "四", "五"],
    [" 前后有空白 ", "带\n换行"],
]
for i, case in enumerate(battery):
    a = E.clean_points(case)
    b = G.clean_points(case)
    c = B.clean_points(case)
    check(f"R8 case#{i} enrich==generate_outputs==build_dashboard",
          a == b == c, f"enrich={a[:1]} go={b[:1]} bd={c[:1]}")

print(f"R8 三处阈值常量一致检查")
check("R8 HARD_MAX 一致",
      E.POINT_HARD_MAX == G.POINT_HARD_MAX == B.POINT_HARD_MAX,
      f"{E.POINT_HARD_MAX}/{G.POINT_HARD_MAX}/{B.POINT_HARD_MAX}")
check("R8 DROP_OVER 一致",
      E.POINT_DROP_OVER == G.POINT_DROP_OVER == B.POINT_DROP_OVER,
      f"{E.POINT_DROP_OVER}/{G.POINT_DROP_OVER}/{B.POINT_DROP_OVER}")

print()
if FAIL:
    print(f"❌ {len(FAIL)} 项未通过：" + " / ".join(FAIL))
    sys.exit(1)
print("✅ 全部通过")
