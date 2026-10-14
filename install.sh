#!/usr/bin/env bash
# 一键安装（macOS / Linux）
# 用法：bash install.sh [--with-model]
set -euo pipefail
cd "$(dirname "$0")"

echo "=== 抖音收藏知识库 · 安装 ==="

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    v=$("$c" -c 'import sys;print("%d.%d"%sys.version_info[:2])')
    case "$v" in 3.1[0-9]|3.[2-9][0-9]) PY="$c"; break;; esac
  fi
done
if [ -z "$PY" ]; then
  echo "!! 未找到 Python 3.10+，请先安装" >&2
  exit 1
fi
echo "使用解释器：$PY ($($PY --version 2>&1))"

[ -d .venv ] || "$PY" -m venv .venv
VENV_PY=".venv/bin/python"

# 国内环境自动走镜像（可用 PIP_INDEX_URL 覆盖）
: "${PIP_INDEX_URL:=https://mirrors.aliyun.com/pypi/simple/}"
echo "pip 源：$PIP_INDEX_URL"
"$VENV_PY" -m pip install --upgrade pip -q
"$VENV_PY" -m pip install -r requirements.txt -q -i "$PIP_INDEX_URL" --trusted-host "$(echo "$PIP_INDEX_URL" | awk -F/ '{print $3}')"

"$VENV_PY" -m playwright install chromium

if [ "${1:-}" = "--with-model" ]; then
  "$VENV_PY" -m pip install modelscope -q -i "$PIP_INDEX_URL"
  "$VENV_PY" run.py fetch-model
fi

echo ""
echo "✅ 安装完成。接下来："
echo "   .venv/bin/python run.py all      # 开始整理（首次会弹出浏览器扫码登录）"
echo "   或先看演示：直接用浏览器打开 demo/index.html"
