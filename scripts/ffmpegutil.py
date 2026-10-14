# -*- coding: utf-8 -*-
"""统一的 ffmpeg 定位工具。

本项目**不依赖系统 ffmpeg**：
  1. 优先用 imageio-ffmpeg 自带的二进制（`pip install imageio-ffmpeg` 即可）；
  2. 找不到再扫 Playwright 自带的 ffmpeg（`playwright install` 会装一份）；
  3. 都没有则给出一条明确的安装指引并退出。

用法：
    from ffmpegutil import get_ffmpeg
    FFMPEG = get_ffmpeg()
"""
from __future__ import annotations

import glob
import os
from pathlib import Path


def _candidates() -> list[str]:
    home = Path.home()
    pats = [
        # Playwright 自带的 ffmpeg（Windows / macOS / Linux）
        str(home / "AppData" / "Local" / "ms-playwright" / "ffmpeg*" / "**" / "ffmpeg*"),
        str(home / "Library" / "Caches" / "ms-playwright" / "ffmpeg*" / "**" / "ffmpeg*"),
        str(home / ".cache" / "ms-playwright" / "ffmpeg*" / "**" / "ffmpeg*"),
        # 系统级
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
    ]
    out: list[str] = []
    for p in pats:
        out.extend(sorted(glob.glob(p, recursive=True)))
    return out


def get_ffmpeg() -> Path:
    """返回可执行的 ffmpeg 路径；找不到时抛出 SystemExit 并给出安装指引。"""
    # 1) imageio-ffmpeg（首选，跨平台自带二进制）
    try:
        import imageio_ffmpeg  # type: ignore

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return Path(exe)
    except Exception:
        pass

    # 2) 环境变量显式指定
    env = os.environ.get("FFMPEG_BINARY") or os.environ.get("FFMPEG_PATH")
    if env and Path(env).exists():
        return Path(env)

    # 3) 扫 Playwright / 系统
    for c in _candidates():
        p = Path(c)
        if p.is_file() and (p.name.lower().startswith("ffmpeg")):
            return p

    raise SystemExit(
        "找不到 ffmpeg。请先安装：\n"
        "    pip install imageio-ffmpeg\n"
        "imageio-ffmpeg 会自带一份 ffmpeg 二进制，无需系统安装。\n"
        "（也可用环境变量 FFMPEG_BINARY 指向你已有的 ffmpeg。）"
    )


if __name__ == "__main__":
    print(get_ffmpeg())
