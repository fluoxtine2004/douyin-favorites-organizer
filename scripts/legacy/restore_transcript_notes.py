# -*- coding: utf-8 -*-
"""回补 vault 笔记的「## 📄 逐字稿」段（修复坑位 P 造成的内容丢失）

背景：`clean_fake_notes.py` 旧实现逐行删「正文 ≤8 字」的行，把真实逐字稿里的短句
也删了（全库 355 篇缺行、共缺 45659 行，98% 是短句）。本脚本按 `favorites.json`
里**原文**重建每篇笔记的逐字稿段。

安全边界（只动逐字稿段）：
  - 只改「## 📄 逐字稿」到下一个「## 」之间的内容
  - AI 要点 / 关键帧截图 / 我的批注 / frontmatter 一律不碰
  - 只处理「该视频确实有逐字稿」的笔记；无逐字稿的保持原样（含占位说明）
  - 运行前先备份 vault（--backup 默认开启）

用法：python restore_transcript_notes.py [--dry]
"""
import glob
import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / "vault"
DATA = ROOT / "data"
CALL = "> [!abstract]- 整理后的全文（点击展开）"
DRY = "--dry" in sys.argv


def log(m):
    print(m, flush=True)


def main():
    fav = json.loads((DATA / "favorites.json").read_text(encoding="utf-8"))
    by_url = {}
    for f in fav.get("folders", []):
        for v in f.get("videos", []):
            if v.get("url"):
                by_url.setdefault(v["url"], v)

    if not DRY:
        dst = DATA / "_backup" / f"vault_prerestore-{time.strftime('%Y%m%d-%H%M%S')}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(VAULT, dst / "vault")
        log(f"备份 → {dst}")

    fixed = skipped_ok = no_trans = miss = 0
    restored_lines = 0
    for fp in glob.glob(str(VAULT / "**" / "*.md"), recursive=True):
        if fp.endswith("README.md"):
            continue
        txt = open(fp, encoding="utf-8").read()
        lines = txt.splitlines()
        m = re.search(r"^原链接:\s*(\S+)\s*$", txt, re.M)
        if not m:
            continue
        v = by_url.get(m.group(1))
        if not v:
            miss += 1
            continue
        tr = (v.get("transcript") or "").strip()
        if not tr:
            no_trans += 1
            continue                      # 无逐字稿 → 不动（可能是豁免占位）
        start = end = None
        for k, ln in enumerate(lines):
            if ln.strip().startswith("## ") and "逐字稿" in ln:
                start = k
                break
        if start is None:
            continue
        for k in range(start + 1, len(lines)):
            if lines[k].startswith("## "):
                end = k
                break
        if end is None:
            end = len(lines)
        want = ["", CALL] + ["> " + ln for ln in tr.splitlines() if ln.strip()] + [""]
        if lines[start + 1:end] == want:
            skipped_ok += 1
            continue
        before = len(lines[start + 1:end])
        restored_lines += max(0, len([x for x in want if x.strip()]) - len(
            [x for x in lines[start + 1:end] if x.strip().startswith("> [")]))
        if not DRY:
            open(fp, "w", encoding="utf-8").write(
                "\n".join(lines[:start + 1] + want + lines[end:]))
        fixed += 1
        if fixed <= 5:
            log(f"  ~ {Path(fp).name[:40]}  逐字稿段 {before} 行 → {len(want)} 行")

    log(f"回补完成：重建 {fixed} 篇；已是最新 {skipped_ok} 篇；"
        f"无逐字稿跳过 {no_trans} 篇；找不到视频 {miss} 篇")
    if DRY:
        log("（--dry，未写盘）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
