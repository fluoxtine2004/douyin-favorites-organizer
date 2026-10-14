# 一键安装（Windows PowerShell）
# 用法：powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== 抖音收藏知识库 · 安装 ===" -ForegroundColor Cyan

# 1) 检查 Python
$py = $null
foreach ($c in @("python", "python3", "py")) {
    try { $v = & $c --version 2>&1; if ($v -match "3\.(1[0-9])") { $py = $c; break } } catch {}
}
if (-not $py) {
    Write-Host "!! 未找到 Python 3.10+，请先安装：https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}
Write-Host "使用解释器：$py ($(& $py --version))"

# 2) 创建虚拟环境
if (-not (Test-Path ".venv")) { & $py -m venv .venv }
$venvPy = ".\.venv\Scripts\python.exe"

# 3) 安装依赖（国内用户默认走阿里云镜像）
$index = "-i", "https://mirrors.aliyun.com/pypi/simple/", "--trusted-host", "mirrors.aliyun.com"
& $venvPy -m pip install --upgrade pip @index | Out-Null
& $venvPy -m pip install -r requirements.txt @index

# 4) 安装浏览器内核
& $venvPy -m playwright install chromium

# 5) 可选：下载 whisper 模型（不装则首次转写自动从 HuggingFace 拉取）
if ($args -contains "--with-model") {
    & $venvPy -m pip install modelscope @index
    & $venvPy run.py fetch-model
}

Write-Host ""
Write-Host "✅ 安装完成。接下来：" -ForegroundColor Green
Write-Host "   .\.venv\Scripts\python.exe run.py all      # 开始整理（首次会弹浏览器扫码登录）"
Write-Host "   或先看演示：直接双击 demo\index.html"
