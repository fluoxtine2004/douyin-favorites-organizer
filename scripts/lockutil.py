# -*- coding: utf-8 -*-
"""流水线互斥锁：避免多个脚本同时写 favorites.json 造成相互覆盖
规则：锁文件记录 PID + 时间 + 任务名；若 PID 已不存在（脚本崩溃残留）则视为过期，自动接管。

⚠ 坑位 Y（2026-10-10 踩过，造成两个进程并发写 favorites.json）：
  原实现用 `subprocess.run(["tasklist", "/FI", f"PID eq {pid}"])` 判活。
  **在 Git Bash 下 `/FI` 会被 MSYS 路径改写机制破坏**（变成 `D:/tool/.../PortableGit/FI`），
  tasklist 直接报「无效参数」并以 exit 1 退出；而 `_pid_alive` 只查 `str(pid) in stdout`，
  错误信息里当然没有 PID → 返回 False → 锁被误判为过期 → 第二个进程抢锁成功。
  修法：① 优先用 `os.kill(pid, 0)`（Windows 上同样可用，且不依赖外部命令）；
        ② 兜底用 PowerShell/cmd 的 tasklist，并**同时检查 returncode**。
"""
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "data" / ".pipeline.lock"
STALE_SEC = 4 * 3600  # 超过 4 小时视为过期锁


def _pid_alive(pid: int) -> bool:
    """判断进程是否存活（Windows 安全版）。

    ⚠ 坑位 Y 之二（2026-10-10 二次踩）：
      `os.kill(pid, 0)` 在 Windows 对「活着但不属于当前进程组」的进程会抛
      `OSError errno=22 (EINVAL)`，**不是 EPERM**。用「errno != EPERM 就判死」
      会把正在跑的批处理误判成已退出 → 锁被清 → 并发写。
      正确做法：Windows 用 `OpenProcess` + `GetExitCodeProcess`（STILL_ACTIVE=259）。
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            k = ctypes.windll.kernel32
            h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False          # 打不开句柄 → 进程不存在
            try:
                code = ctypes.c_ulong()
                if k.GetExitCodeProcess(h, ctypes.byref(code)):
                    return code.value == 259   # STILL_ACTIVE
                return False
            finally:
                k.CloseHandle(h)
        except Exception:
            return True               # 判断不了 → 保守当活着
    # POSIX
    try:
        os.kill(pid, 0)
        return True
    except OSError as e:
        import errno
        return e.errno == errno.EPERM
    except Exception:
        return True


def acquire(name: str) -> bool:
    if LOCK.exists():
        try:
            parts = LOCK.read_text(encoding="utf-8").split()
            pid, ts = int(parts[0]), float(parts[1])
            alive = _pid_alive(pid)
            fresh = (time.time() - ts) < STALE_SEC
            if alive and fresh:
                print(f"!! 已有流水线任务在运行（{LOCK.read_text(encoding='utf-8').strip()}），本次退出：{name}", flush=True)
                return False
            print(f".. 清理过期锁（pid={pid} alive={alive}）：{name}", flush=True)
        except Exception:
            pass
    LOCK.write_text(f"{os.getpid()} {time.time():.0f} {name}", encoding="utf-8")
    return True


def release():
    try:
        LOCK.unlink()
    except Exception:
        pass
