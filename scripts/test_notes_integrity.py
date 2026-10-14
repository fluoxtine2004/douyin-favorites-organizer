# -*- coding: utf-8 -*-
"""笔记完整性回归守卫（坑位 P）

守两件事：
  1) clean_fake_notes 的判伪必须是**段落级**的，逐行「≤8 字就删」的老规则不许回来；
  2) vault 里凡「有真实逐字稿」的笔记，逐字稿段必须与 favorites.json 的原文逐行一致
     （唯一例外：整段确属伪转写 / 无意义碎片 → 允许写占位说明）。

用法：python scripts/test_notes_integrity.py
"""
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import clean_fake_notes as C  # noqa: E402

FAIL = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   {detail}" if detail and not ok else ""))
    if not ok:
        FAIL.append(name)


print("P1 段落判伪单测（真实逐字稿带短句 → 不许判伪）")
real_short = ["", "> [!abstract]- 整理后的全文（点击展开）",
              "> [00:43] 它的帮助中心里面写的比较直白",
              "> [00:46] 它不接受学生证",
              "> [00:47] 也不接受其他文件来证明身份",
              "> [00:49] 而且你学校的邮箱",
              "> [00:51] 还必须是你的主邮箱"]
check("P1 短句多的真实逐字稿不被判伪", C.section_is_fake(real_short) is False)

wm = ["", "> [!abstract]- x", "> [00:01] 字幕by索兰娅", "> [00:02] 字幕by索兰娅"]
check("P1 含水印 → 判伪", C.section_is_fake(wm) is True)

frag = ["", "> [00:00] 三 二 一", "> [00:03] 再坚持", "> [00:04] 再坚持", "> [00:06] 嗯"]
check("P1 整段无意义碎片 → 判伪", C.section_is_fake(frag) is True)

check("P1 空段落不判伪", C.section_is_fake([]) is False)

print("P2 逐行删除规则已移除（老 bug 不许回来）")
src = (ROOT / "scripts" / "clean_fake_notes.py").read_text(encoding="utf-8")
check("P2 逐行判据 fake_line 已不存在",
      ("def fake_line" not in src) and ("fake_line(" not in src))
check("P2 逐行删除已不存在（只允许按整段替换）",
      "i += 1; continue" not in src or "section_is_fake" in src)

print("P3 全库不变量：有逐字稿的笔记逐字稿段必须完整")
fav = json.loads((ROOT / "data" / "favorites.json").read_text(encoding="utf-8"))
V, url2id = {}, {}
for f in fav.get("folders", []):
    for v in f.get("videos", []):
        V.setdefault(v["id"], v)
        if v.get("url"):
            url2id.setdefault(v["url"], v["id"])

checked = bad = miss_lines = placeholder_ok = 0
worst = []
for fp in glob.glob(str(ROOT / "vault" / "**" / "*.md"), recursive=True):
    if fp.endswith("README.md"):
        continue
    txt = open(fp, encoding="utf-8").read()
    m = re.search(r"^原链接:\s*(\S+)\s*$", txt, re.M)
    if not m:
        continue
    vid = url2id.get(m.group(1))
    if not vid or not V[vid].get("transcript"):
        continue
    checked += 1
    exp = [l for l in V[vid]["transcript"].splitlines() if l.strip()]
    i = txt.find("## 📄 逐字稿")
    j = txt.find("\n## ", i + 5)
    seg = txt[i:j if j > 0 else len(txt)]
    missing = [l for l in exp if l not in seg]
    if missing:
        if C.PLACEHOLDER in seg:              # 确属伪转写 → 写占位说明是允许的
            placeholder_ok += 1
            continue
        bad += 1
        miss_lines += len(missing)
        if len(worst) < 3:
            worst.append((Path(fp).name[:34], len(missing), missing[:2]))
check(f"P3 {checked} 篇有逐字稿的笔记全部完整", bad == 0,
      f"{bad} 篇缺 {miss_lines} 行 {worst}")
print(f"        （其中 {placeholder_ok} 篇为「确属伪转写 → 占位说明」的合法例外）")

print()
if FAIL:
    print(f"❌ {len(FAIL)} 项未通过：" + " / ".join(FAIL))
    sys.exit(1)
print("✅ 全部通过")
