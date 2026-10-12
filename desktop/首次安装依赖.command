#!/usr/bin/env bash
# 首次安装 Python 依赖 + Playwright Chromium（只需跑一次）。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$HERE/requirements.txt" ] && [ -f "$HERE/desktop/app.py" ]; then
  ROOT="$HERE"
elif [ -f "$HERE/../requirements.txt" ] || [ -f "$HERE/../archgen.py" ]; then
  ROOT="$(cd "$HERE/.." && pwd)"
else
  ROOT="$(cd "$HERE/.." && pwd)"
fi

cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  osascript -e 'display alert "未找到 python3" message "请先从 https://www.python.org/downloads/ 安装 Python 3.10 或更高版本。"' 2>/dev/null || true
  exit 1
fi

REQ="$ROOT/requirements.txt"
if [ ! -f "$REQ" ]; then
  echo "找不到 requirements.txt：$REQ" >&2
  exit 1
fi

echo ">>> 目录：$ROOT"
echo ">>> Python：$(python3 --version)"
echo ">>> 安装依赖…"
python3 -m pip install -r "$REQ"
echo ">>> 安装截图浏览器 Chromium…"
python3 -m playwright install chromium

mkdir -p userdata/diagrams userdata/logs
echo ""
echo "安装完成。请双击「启动 ArchGen.command」打开界面。"
read -r -p "按回车关闭…" _
