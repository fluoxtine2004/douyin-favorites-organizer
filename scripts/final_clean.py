# -*- coding: utf-8 -*-
"""
收尾清理：在 process_batch 转写完成后执行
  1. 标记白噪音/纯音乐为 no_transcript（不浪费下次转写）
  2. 清理 digg / collect_count（用户不要点赞数据）
用法：python scripts/final_clean.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "favorites.json"

NOISE_KW = ['白噪音', '助眠', '雷雨', '暴雨', '雨声', '声波镇定', '调节身心', '睡眠',
            '钢琴', '小提琴', '英文歌', 'livehouse', '圣诞结', 'IFallApart', 'BGM',
            '音乐', '耳语', '疗愈', '频率', '深度放松', '掩蔽']


def main():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    marked = digg = 0
    for f in d.get("folders", []):
        for v in f.get("videos", []):
            if not v.get("transcript"):
                t = (v.get("title") or "")
                if any(k in t for k in NOISE_KW):
                    v["no_transcript"] = "noise_music"
                    marked += 1
            if "digg" in v:
                v.pop("digg", None)
                v.pop("collect_count", None)
                digg += 1
    DATA.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ 收尾清理：标记白噪音 {marked} 条，清理 digg {digg} 条")


if __name__ == "__main__":
    main()
