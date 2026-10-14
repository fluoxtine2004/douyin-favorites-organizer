# -*- coding: utf-8 -*-
"""质量守门：转发到 scripts/test_render.py（原实现保留在 scripts/ 以便共享 import）。

跑法：python tests/test_render.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts" / "test_render.py"
sys.exit(subprocess.run([sys.executable, str(TARGET)]).returncode)
