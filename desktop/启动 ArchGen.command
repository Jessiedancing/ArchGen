#!/usr/bin/env bash
# 双击即可启动 ArchGen 本地绿色版（Mac）。
# 可放在绿色包根目录，或 desktop/ 子目录。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$HERE/desktop/app.py" ]; then
  ROOT="$HERE"
elif [ -f "$HERE/app.py" ] && [ -f "$HERE/../archgen.py" ]; then
  ROOT="$(cd "$HERE/.." && pwd)"
else
  osascript -e 'display alert "找不到 ArchGen" message "请确认本脚本与 archgen.py、desktop/app.py 在同一绿色包内。"' 2>/dev/null || \
    echo "找不到 ArchGen 目录结构" >&2
  exit 1
fi

cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  osascript -e 'display alert "未找到 python3" message "请先安装 Python 3.10+，或运行「首次安装依赖.command」查看说明。"' 2>/dev/null || true
  exit 1
fi

if ! python3 -c "import openai, httpx" 2>/dev/null; then
  osascript -e 'display alert "依赖未安装" message "请先双击运行「首次安装依赖.command」，完成后再启动。"' 2>/dev/null || true
  exit 1
fi

mkdir -p userdata/diagrams userdata/logs
exec python3 desktop/app.py
