# -*- coding: utf-8 -*-
"""
转写 → 补帧 → 重建产出 → 校验 一条龙（2026-10-10 建立）

用途：把「批量转写 → 给豁免条目补关键帧 → 走清洗链重建产出并校验」串成一次后台长跑。
为什么单独写：主批 `batch_transcribe.py` 全量约 22 小时（坑位 W），期间要拿锁；
补帧与重建产出必须等它完全结束后再跑，否则会抢锁 / 读到写了一半的 favorites.json。

用法：
  python scripts/finish_transcribe_chain.py --wait-lock   # 先等主批释放锁（推荐）
  python scripts/finish_transcribe_chain.py --skip-transcribe  # 跳过转写，只补帧+重建
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PY = Path(sys.executable)
LOGS = ROOT / "logs"
LOCK_DIR = ROOT / "data"


def log(msg):
    print(msg, flush=True)


def run(script, tag, extra=None, timeout=None):
    cmd = [str(PY), str(SCRIPTS / script)] + (extra or [])
    log(f"\n{'=' * 60}\n▶ {tag}\n  {' '.join(cmd)}\n{'=' * 60}")
    t0 = time.time()
    with open(LOGS / f"chain_{tag}.log", "w", encoding="utf-8") as f:
        try:
            r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
            rc = r.returncode
        except subprocess.TimeoutExpired:
            rc = -1
            f.write("\n!! TIMEOUT\n")
    log(f"  → {tag} 退出码 {rc}，耗时 {time.time() - t0:.0f}s")
    return rc


def _pid_alive(pid: int) -> bool:
    """与 lockutil 完全同款（Windows 用 OpenProcess，别用 os.kill）"""
    sys.path.insert(0, str(SCRIPTS))
    from lockutil import _pid_alive as impl
    return impl(pid)


def log_done(logpath: Path) -> bool:
    """批处理日志里是否出现「批次完成」"""
    try:
        if not logpath.exists():
            return False
        tail = logpath.read_text(encoding="utf-8", errors="ignore")[-4000:]
        return "批次完成" in tail
    except Exception:
        return False


# 读文件失败时的哨兵：主批写盘瞬间读会抛异常，绝不能把「读不到」当成「没活了」
# （坑位 AC：上一次收尾链正是把 -1 当成「剩余<=0」而提前触发，实际主批还在跑）
_UNKNOWN = -1
_last_ok = None


def remaining_count() -> int:
    """favorites.json 里仍待转写（无 transcript 且无 no_transcript）的条数。

    读失败（主批正在写盘）时返回上一次的有效值；从未读到过则返回哨兵 _UNKNOWN，
    由调用方按「未知 = 不结束」处理。
    """
    import json
    global _last_ok
    try:
        d = json.loads((ROOT / "data" / "favorites.json").read_text(encoding="utf-8"))
        n = sum(1 for f in d.get("folders", []) for v in f.get("videos", [])
                if not v.get("transcript") and not v.get("no_transcript"))
        _last_ok = n
        return n
    except Exception:
        # 读不到就用上次有效值；如果连上次都没有，返回 -1 让调用方知道「未知」
        return _last_ok if _last_ok is not None else _UNKNOWN


def lock_free():
    """锁是否空闲。直接读锁文件 + _pid_alive（不再试探性 acquire，那只删真锁）。"""
    lock = LOCK_DIR / ".pipeline.lock"
    if not lock.exists():
        return True
    try:
        parts = lock.read_text(encoding="utf-8").split()
        return not _pid_alive(int(parts[0]))
    except Exception:
        return True


def main():
    wait_lock = "--wait-lock" in sys.argv
    skip_tr = "--skip-transcribe" in sys.argv

    if not skip_tr:
        log("等待主批完成（同时看锁与剩余条数）…")
        waited = 0
        while True:
            free = lock_free()
            rem = remaining_count()
            # 只有「锁空闲」且「确定剩余为 0」才结束。
            # rem < 0 表示读不到 favorites.json（未知），绝不能当结束（坑位 AC）。
            if free and rem == 0:
                log(f"锁已释放且无待转写（剩余 {rem}），继续。")
                break
            if waited >= 36 * 3600:
                log(f"等待超时（36h），缓冲区状态：锁空闲={free} 剩余={rem}，继续执行后续步骤。")
                break
            if waited % 1800 == 0:
                flag = "未知" if rem < 0 else rem
                log(f"  仍在跑… 锁空闲={free} 剩余待转写={flag} 已等 {waited // 60} 分钟")
            time.sleep(120)
            waited += 120

    # 0) 回填要点（早期进程用的旧切分逻辑，要点恒为空 → 重算）
    run("backfill_points.py", "backfill_points")

    # 1) 补关键帧（豁免条目 / 有稿但缺帧）
    run("batch_transcribe.py", "frames", extra=["--frames-only"])

    # 2) 清洗链
    for s in ["final_clean.py", "clean_fake_transcripts.py", "refill_enriched.py",
              "generate_outputs.py", "clean_fake_notes.py", "recover_notes.py",
              "build_topics.py"]:
        run(s, s.replace(".py", ""))

    # 3) 收藏次序 + 产出
    run("build_collect_index.py", "build_collect_index")
    run("generate_outputs.py", "generate_outputs_final")
    run("build_site.py", "build_site")

    # 4) 校验
    for s in ["final_verify.py", "test_render.py", "test_new_features.py",
              "test_points_rules.py", "test_notes_integrity.py"]:
        run(s, "test_" + s.replace(".py", "").replace("test_", ""))

    log("\n全链完成。")


if __name__ == "__main__":
    main()
