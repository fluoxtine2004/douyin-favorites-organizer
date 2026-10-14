# -*- coding: utf-8 -*-
"""交付前完整自查：数据完整性 / 点赞污染 / 转写覆盖 / 孤儿笔记 / 站点产物"""
import json, os, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')
DIST = os.path.join(BASE, 'dist')

print('=' * 60)
print('1. favorites.json 数据源自查')
print('=' * 60)
fav = json.load(open(os.path.join(DATA, 'favorites.json'), encoding='utf-8'))
folders = fav.get('folders', [])
print(f'文件夹数: {len(folders)}')
allv = {}
for f in folders:
    for v in f.get('videos', []):
        allv[v['id']] = v
print(f'视频总数: {len(allv)}')
with_t = sum(1 for v in allv.values() if (v.get('transcript') or '').strip())
noise = sum(1 for v in allv.values() if v.get('no_transcript'))
no_t = len(allv) - with_t
print(f'有逐字稿: {with_t} ({with_t*100//len(allv)}%)  无逐字稿: {no_t} (标记豁免: {noise})')
bad = [v['id'] for v in allv.values() if 'digg_count' in v or 'collect_count' in v]
print(f'残留 digg/collect 字段: {len(bad)}')
dup = len(allv) - len(set(allv))
print(f'ID 重复: {dup}')
# 每个文件夹内视频ID是否有跨夹重复
seen = {}
dups = []
for f in folders:
    for v in f.get('videos', []):
        if v['id'] in seen:
            dups.append((v['id'], seen[v['id']], f.get('name')))
        else:
            seen[v['id']] = f.get('name')
print(f'跨文件夹重复: {len(dups)}')
for d in dups[:10]:
    print('   ', d)

print()
print('=' * 60)
print('2. 转写内容抽查（长度分布）')
print('=' * 60)
lens = sorted((len(v.get('transcript') or '') for v in allv.values()), reverse=True)
if lens:
    print(f'最长: {lens[0]} 字  最短非空: {min(l for l in lens if l>0)}  中位数: {lens[len(lens)//2]}')
empty_ids = [v['id'] for v in allv.values() if not (v.get('transcript') or '').strip() and not v.get('no_transcript')]
print(f'无转写且未标记豁免: {len(empty_ids)}')
for i in empty_ids[:20]:
    v = allv[i]
    print(f'   {i} | {v.get("title","")[:40]} | {v.get("author","")}')

print()
print('=' * 60)
print('3. enriched.json 一致性')
print('=' * 60)
enr = json.load(open(os.path.join(DATA, 'enriched.json'), encoding='utf-8'))
print(f'enriched 条目: {len(enr)}  收藏视频数: {len(allv)}')
missing = [i for i in allv if i not in enr]
extra = [i for i in enr if i not in allv]
print(f'favorites 有但 enriched 缺: {len(missing)}')
print(f'enriched 有但 favorites 缺: {len(extra)}')
no_sum = [k for k, v in enr.items() if not (v.get('summary') or '').strip()]
print(f'无 summary: {len(no_sum)}')

print()
print('=' * 60)
print('4. 站点产物 dist 自查')
print('=' * 60)
dj = json.load(open(os.path.join(DIST, 'data.json'), encoding='utf-8'))
# data.json 结构可能是 {videos: [...]} 或 dict
if isinstance(dj, dict) and 'videos' in dj:
    dv = dj['videos']
elif isinstance(dj, list):
    dv = dj
else:
    dv = list(dj.values()) if isinstance(dj, dict) else []
print(f'dist data.json 视频数: {len(dv)}')
bad2 = [v.get('id') for v in dv if 'digg_count' in v or 'collect_count' in v]
print(f'dist 残留 digg/collect: {len(bad2)}')
no_t2 = sum(1 for v in dv if not (v.get('transcript') or '').strip())
print(f'dist 无逐字稿: {no_t2}')
# 媒体文件存在性抽查
media_dir = os.path.join(DIST, 'media')
if os.path.isdir(media_dir):
    media_files = os.listdir(media_dir)
    print(f'media 文件数: {len(media_files)}')
else:
    print('media 目录不存在!')

print()
print('=' * 60)
print('5. Obsidian vault 自查')
print('=' * 60)
vault = os.path.join(BASE, 'vault')
if os.path.isdir(vault):
    notes = [f for f in os.listdir(vault) if f.endswith('.md')]
    print(f'笔记数: {len(notes)}')
    like_notes = []
    for n in notes:
        p = os.path.join(vault, n)
        try:
            txt = open(p, encoding='utf-8').read()
        except Exception:
            txt = ''
        if '点赞:' in txt:
            like_notes.append(n)
    print(f'含"点赞:"字段的笔记: {len(like_notes)}')
    # 孤儿检查：笔记文件名是否为视频ID
    note_ids = set(n[:-3] for n in notes)
    orphan = note_ids - set(allv.keys())
    print(f'孤儿笔记(不在favorites中): {len(orphan)}')
else:
    print('vault 目录不存在!')

print()
print('全部自查完成')
