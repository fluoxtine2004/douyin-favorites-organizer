# -*- coding: utf-8 -*-
import json, re, glob, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / "vault"

print("="*60); print("A. favorites.json 数据源"); print("="*60)
fav = json.load(open(ROOT/"data"/"favorites.json", encoding="utf-8"))
allv={}
for f in fav.get("folders",[]):
    for v in f.get("videos",[]): allv[v["id"]]=v
print(f"唯一视频: {len(allv)}")
digg=[i for i,v in allv.items() if 'digg_count' in v or 'collect_count' in v]
print(f"残留 digg/collect: {len(digg)}")
TS=re.compile(r'\[\d{1,2}:\d{2}(?::\d{2})?\]'); PUNCT=re.compile(r'[\s，。、！？…—,.\!\?~"\'：:；;（）()\[\]【】\-\u3000]')
def rl(t): s=TS.sub('',t); return len(s)-len(PUNCT.findall(s))
real=set(i for i,v in allv.items() if (v.get('transcript') or '').strip() and rl(v['transcript'])>15)
print(f"有真实转写(>15字): {len(real)}  | 无语音/豁免: {len(allv)-len(real)}")

print("\n"+"="*60); print("B. dist/data.json 产物"); print("="*60)
d=json.load(open(ROOT/"dist"/"data.json", encoding="utf-8"))
print(f"条目: {len(d)} | has_transcript=True: {sum(1 for v in d if v.get('has_transcript'))} | False: {sum(1 for v in d if v.get('has_transcript')==False)}")

print("\n"+"="*60); print("C. vault 笔记质量"); print("="*60)
wm=re.compile(r'字幕\s*by|subtitle by',re.I)
PLACE="本视频无语音内容（纯音乐 / 画面为主），无逐字稿。"
bad_wm=0; suspect_place=0; total=0
for fp in VAULT.rglob("*.md"):
    if str(fp).endswith("README.md"): continue
    total+=1
    t=open(fp,encoding='utf-8').read()
    for m in re.finditer(r'## 📄 逐字稿(.*?)(?=## )',t,re.S):
        if wm.search(m.group(1)): bad_wm+=1
    if PLACE in t:
        mm=re.search(r'/video/(\d+)',t); vid=mm.group(1) if mm else None
        if vid is None or vid in real: suspect_place+=1
print(f"笔记总数: {total}")
print(f"逐字稿段含水印: {bad_wm} (应=0)")
print(f"真实笔记残留占位行: {suspect_place} (应=0)")

print("\n"+"="*60); print("D. 周报必需章节"); print("="*60)
fp=sorted(glob.glob(str(VAULT/'00-周报'/'Week*.md')))[-1]
t=open(fp,encoding='utf-8').read()
# ⚠ 2026-10-11：周报主体已改为「各收藏夹新增 + 本期新增 + 整体回顾 + 待办」，
#   旧的「学习的/执行的/了解的/可运行的」四段式断言已过时（会误报 ❌）。
need=['## 各收藏夹新增','# 📋','本期整理']
for s in need:
    print(('  ✅' if s in t else '  ❌'), s)

print("\n"+"="*60); print("E. 逐字稿笔记抽查（水印 = 异常）"); print("="*60)
checked=0; mark_hits=0; place_cnt=0
for fp in sorted(VAULT.rglob("*.md")):
    if str(fp).endswith("README.md"): continue
    tt=open(fp,encoding='utf-8').read()
    seg=re.search(r'## 📄 逐字稿(.*?)(?=## )',tt,re.S)
    if not seg: continue
    body=seg.group(1)
    if wm.search(body): mark_hits+=1
    if PLACE in body: place_cnt+=1
    checked+=1
print(f"  含逐字稿段笔记: {checked}")
print(f"  含水印(异常): {mark_hits} (应=0)")
print(f"  无语音占位: {place_cnt} (正常——属已豁免的「纯音乐/画面为主」)")
print("\n全部校验完成。")
