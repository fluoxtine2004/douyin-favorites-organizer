# -*- coding: utf-8 -*-
import json, os, sys, io, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fav = json.load(open(os.path.join(ROOT,'data','favorites.json'), encoding='utf-8'))
newids = json.load(open(os.path.join(ROOT,'data','new_ids.json'), encoding='utf-8'))['ids']
by = {}
for f in fav.get('folders', []):
    for v in f.get('videos', []):
        by.setdefault(str(v.get('id')), []).append(v)
MEDIA = os.path.join(ROOT,'media')
for vid in newids:
    vs = by.get(str(vid))
    if not vs:
        print(f'{vid}  NOT_IN_FAV')
        continue
    for v in vs:
        tr = (v.get('transcript') or '').strip()
        d = os.path.join(MEDIA, str(vid))
        frames = []
        if os.path.isdir(d):
            frames = sorted(os.path.basename(x) for x in glob.glob(os.path.join(d,'*.jpg')))[:4]
            nmp4 = len(glob.glob(os.path.join(d,'*.mp4')))
            nwav = len(glob.glob(os.path.join(d,'*.wav')))
        else:
            nmp4=nwav=0
        print(f"{vid} | tr={len(tr):5d} | no_tr={bool(v.get('no_transcript'))} | no_frames={v.get('no_frames')} | dl_fail={v.get('dl_failed_recently')} | mp4={nmp4} wav={nwav} | frames={len(frames)} {frames[:2]} | {str(v.get('title'))[:30]}")
