# -*- coding: utf-8 -*-
"""
收尾脚本：处理 9 条 process_batch 判为"空转写"的视频。
原因：process_batch 固定 language=zh + vad_filter=True，对英文/音乐/纯BGM视频
会返回 0 字且不持久化结果，导致卡死。
本脚本：
  - 复用 media/<id>/audio.wav（diag 已抽取），避免重新下载
  - 用 auto 语言 + vad_filter=False 多配置转写，取最长结果
  - 若纯文本 >=15 字 → 写入带时间戳 transcript + points + frames
  - 否则 → 标记 no_transcript="no_speech_or_music"，清空 transcript
仅修改 favorites.json（enriched 由后续 enrich.py 重建）。
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(r"\scripts")))
import process_batch as pb

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "favorites.json"
RETRY = ROOT / "data" / "_retry_ids.json"
MEDIA = ROOT / "media"

LANG_CONFIGS = [None, "zh", "en"]  # None=auto
MIN_REAL = 15

# 伪转写特征（水印/字幕署名/制作 credits/乱码）
FAKE_PAT = re.compile(
    r"字幕\s*by|字幕组|@[\u4e00-\u9fff]+字幕|听译|机翻|翻译\s*by|subtitle|субтитр|"
    r"詞曲|作曲|编曲|演唱\s*[:：]|出品|MING\s*PAO|EDITOR|CREDIT|时间轴|校对",
    re.I)


def ts(sec):
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def is_fake(text):
    if FAKE_PAT.search(text):
        return True
    # 同一 2~4 字子串重复 >=10 次且占文本 >50% → 乱码（如 BITBITBIT…）
    for L in (2, 3, 4):
        c = {}
        for i in range(len(text) - L + 1):
            sub = text[i:i + L]
            c[sub] = c.get(sub, 0) + 1
        if c:
            top, cnt = max(c.items(), key=lambda kv: kv[1])
            if cnt >= 10 and cnt * L > 0.5 * len(text):
                return True
    return False


def best_transcribe(model, audio_path):
    best = ("", 0, None, 0)  # text_stamped, plain_len, segs, dur
    for lang in LANG_CONFIGS:
        try:
            segs, info = model.transcribe(str(audio_path), language=lang, vad_filter=False)
            lines, plain = [], []
            for seg in segs:
                t = f"[{ts(seg.start)}] {seg.text.strip()}"
                lines.append(t)
                plain.append(seg.text.strip())
            full = "\n".join(lines)
            pl = "".join(plain)
            if len(pl) > best[1]:
                best = (full, len(pl), segs, info.duration or 0)
        except Exception:
            pass
    return best


def main():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    ids = json.loads(RETRY.read_text(encoding="utf-8"))
    rec = {}
    for f in d["folders"]:
        for v in f["videos"]:
            if v["id"] in ids:
                rec[v["id"]] = v

    model = pb.get_whisper()
    done = silent = 0
    for i in ids:
        v = rec.get(i)
        if not v:
            continue
        wd = MEDIA / i
        wd.mkdir(parents=True, exist_ok=True)
        au = wd / "audio.wav"
        vf = wd / "video.mp4"
        if not au.exists():
            # 兜底重新抽取
            if not vf.exists():
                vf = pb.download_video(v, wd)
            if not vf:
                v["dl_failed_recently"] = time.strftime("%Y-%m-%d %H:%M:%S")
                print(f"  {i} 下载失败，跳过", flush=True)
                continue
            au = pb.extract_audio(vf, wd)
            if not au:
                v["dl_failed_recently"] = time.strftime("%Y-%m-%d %H:%M:%S")
                print(f"  {i} 音频提取失败，跳过", flush=True)
                continue
        stamped, plen, segs, dur = best_transcribe(model, au)
        v.pop("dl_failed_recently", None)
        v.pop("no_play_urls", None)
        plain = "".join(s.text for s in segs) if segs else ""
        if plen >= MIN_REAL and not is_fake(plain):
            v["transcript"] = stamped
            v["points"] = pb.summarize_points("".join(s.text for s in segs), v.get("title", ""))
            if not vf.exists():
                vf = pb.download_video(v, wd)
            fr = pb.extract_frames(vf, wd, dur) if (vf and vf.exists()) else []
            v["frames"] = [{"url": f["path"], "t": f["t"], "cap": f"{f['t']//60}:{f['t']%60:02d}"} for f in fr]
            v["processed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            v["no_transcript"] = ""
            done += 1
            print(f"  ✅ {i} 转写成功（{plen} 字）", flush=True)
        else:
            v["transcript"] = ""
            v["points"] = []
            v["frames"] = []
            v["no_transcript"] = "no_speech_or_music"
            silent += 1
            print(f"  ⭘ {i} 判定无声（{plen} 字）→ no_transcript", flush=True)
        DATA.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n收尾完成：成功转写 {done} / 无声标记 {silent} / 共 {len(ids)}", flush=True)


if __name__ == "__main__":
    main()
