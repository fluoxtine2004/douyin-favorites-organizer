# -*- coding: utf-8 -*-
"""
全量清洗：扫描 vault 所有笔记的 “## 📄 逐字稿” 段落，
凡确属「伪转写」（字幕水印 / 整段都是无意义碎片）的，替换为“无逐字稿”说明。
只改逐字稿段，不动 AI要点 / 我的批注 / 周报叙述中的合法提及。

⚠ 坑位 P（2026-10-08 修）：旧实现是**逐行**判定 `real_len(行) <= 8 → 删该行`，
   结果把真实逐字稿里的短句也全删了（"它不接受学生证" / "但是有的学校" …）。
   全库实测：375 篇有逐字稿的笔记里 355 篇缺行、共缺 45659 行，其中 44779 行（98%）
   正是被这条规则误删的。判定必须**在段落级别**做，绝不逐行删真实内容：
     ① 行内出现字幕水印 → 该行是伪转写；
     ② 整段「无意义碎片」占比 ≥ 60%（real_len ≤ 3 且 ≥3 行）→ 整段判伪；
     ③ 其余情况一行都不动（短句是 whisper 分段的正常形态）。
"""
import re
import glob
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / "vault"

WATERMARK = re.compile(r"字幕\s*by|@[\u4e00-\u9fff]+字幕|subtitle by", re.I)
TS = re.compile(r"\[\d{1,2}:\d{2}(?::\d{2})?\]")
PUNCT = re.compile(r"[\s，。、！？…—,.\!\?~\"'：:；;（）()\[\]【】\-\u3000]")

# ⚠ 坑位 AD（2026-10-11）：原先「碎片占比 ≥60% → 判伪」这条规则是**错的**。
#   whisper 中文转写天然就是「一行一个短语」，实拍生活 vlog（「哇 / 好可愛 / 什麼」）
#   会轻松满足 60% 碎片率 → 被整段替换成占位说明，而 favorites.json 里的真实逐字稿仍在，
#   造成「笔记缺行」的全库不变量失败（实测命中 2 篇，且 2 篇都是真实内容）。
#   修正：碎片规则**只用于极短片段**（≤ FAKE_SHORT_MAX 行），那种才是真·无意义碎片；
#   段落一旦有足够长度（≥ FAKE_MIN_TOTAL 行）就不再靠碎片率判伪，只认水印。
WATERMARK_ONLY_LONG = True
FAKE_FRAG_MAX = 3        # 「无意义碎片」的正文长度上限
FAKE_RATIO = 0.6         # 碎片占比达到多少即判整段为伪转写（仅对极短片段生效）
FAKE_MIN_LINES = 3       # 至少几行碎片才敢判伪
FAKE_SHORT_MAX = 8       # 超过这么多行的段落，一律不靠碎片率判伪（只认水印）

PLACEHOLDER = "> 本视频无语音内容（纯音乐 / 画面为主），无逐字稿。"


def real_len(t: str) -> int:
    s = TS.sub("", t)
    return len(s) - len(PUNCT.findall(s))


def is_watermark(ln: str) -> bool:
    body = ln.lstrip("> ").strip()
    return bool(body) and bool(WATERMARK.search(body))


def content_lines(block):
    """段落里的正文行（去掉 markdown 引用符与空行）"""
    out = []
    for ln in block:
        body = ln.lstrip("> ").strip()
        if body and not body.startswith("[!"):
            out.append((ln, body))
    return out


def section_is_fake(block) -> bool:
    """段落级判伪：水印行 → 伪；极短且满是碎片 → 伪；其余一律保留。

    ⚠ 不再对「长段落」用碎片率判伪（坑位 AD）：whisper 中文一行一短语，
       真实生活 vlog 的碎片率天然很高，按比例判会把真内容整段删掉。
    """
    lines = content_lines(block)
    if not lines:
        return False
    if any(WATERMARK.search(b) for _, b in lines):
        return True
    # 只有「极短片段」（≤ FAKE_SHORT_MAX 行）才允许按碎片率判伪
    if len(lines) > FAKE_SHORT_MAX:
        return False
    frags = [b for _, b in lines if real_len(b) <= FAKE_FRAG_MAX]
    return len(frags) >= FAKE_MIN_LINES and len(frags) / len(lines) >= FAKE_RATIO


def main():
    fixed = skipped = 0
    for fp in glob.glob(str(VAULT / "**" / "*.md"), recursive=True):
        if fp.endswith("README.md"):
            continue
        lines = open(fp, encoding="utf-8").read().splitlines()
        # 定位逐字稿段的 [start, end)
        start = end = None
        for k, ln in enumerate(lines):
            if ln.strip().startswith("## ") and "逐字稿" in ln:
                start = k
                break
        if start is None:
            skipped += 1
            continue
        for k in range(start + 1, len(lines)):
            if lines[k].startswith("## "):
                end = k
                break
        if end is None:
            end = len(lines)
        block = lines[start + 1:end]
        if section_is_fake(block):
            new_block = ["", PLACEHOLDER, ""]
            if new_block != block:
                open(fp, "w", encoding="utf-8").write(
                    "\n".join(lines[:start + 1] + new_block + lines[end:]))
                fixed += 1
                continue
        skipped += 1

    print(f"清洗完成：修改 {fixed} 篇，无需修改 {skipped} 篇")


if __name__ == "__main__":
    main()
