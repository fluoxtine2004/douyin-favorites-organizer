# -*- coding: utf-8 -*-
"""只读巡检：统计收藏转写完成度"""
import json, os, sys, io, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAV = os.path.join(ROOT, 'data', 'favorites.json')
MEDIA = os.path.join(ROOT, 'media')

fav = json.load(open(FAV, encoding='utf-8'))
vids = []
for f in fav.get('folders', []):
    for v in f.get('videos', []):
        vids.append(v)

total = len(vids)
ids = [v.get('id') for v in vids]
uniq = len(set(ids))

have_tr = 0        # 有逐字稿（真）
no_tr = 0          # 无语音豁免
pending = 0        # 待转写
pending_ids = []
no_frames = 0      # 纯音频 no_frames
for v in vids:
    tr = (v.get('transcript') or '').strip()
    is_no = bool(v.get('no_transcript'))
    if tr and not is_no:
        have_tr += 1
    elif is_no:
        no_tr += 1
    else:
        pending += 1
        pending_ids.append(v.get('id'))
    if v.get('no_frames'):
        no_frames += 1

# 真缺帧：有内容（有稿或豁免）但 media/<id> 下无 kf_/img 帧，且未标 no_frames
missing_frames = []
for v in vids:
    vid = v.get('id')
    tr = (v.get('transcript') or '').strip()
    is_no = bool(v.get('no_transcript'))
    if not tr and not is_no:
        continue  # 待转写的跳过
    if v.get('no_frames'):
        continue
    d = os.path.join(MEDIA, str(vid))
    has_frame = False
    if os.path.isdir(d):
        for pat in ('kf_*.jpg', 'img*.jpg'):
            if glob.glob(os.path.join(d, pat)):
                has_frame = True
                break
    if not has_frame:
        missing_frames.append(vid)

print(json.dumps({
    'total_records': total,
    'unique_ids': uniq,
    'folders': len(fav.get('folders', [])),
    'have_transcript': have_tr,
    'no_transcript_exempt': no_tr,
    'pending': pending,
    'pending_ids': pending_ids,
    'no_frames_audio_only': no_frames,
    'missing_frames_content': len(missing_frames),
    'missing_frames_ids': missing_frames[:50],
}, ensure_ascii=False, indent=2))
