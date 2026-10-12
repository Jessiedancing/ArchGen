chcp 65001 >nul
@echo off
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"
if exist "desktop\app.py" goto :have_root
if exist "app.py" cd /d "%~dp0.."
if not exist "desktop\app.py" (
  echo 找不到 ArchGen。请确认本脚本与 archgen.py、desktop\app.py 在同一绿色包内。
  pause
  exit /b 1
)
:have_root
set "ROOT=%cd%"

set "PY="
where python >nul 2>&1
if not errorlevel 1 set "PY=python"
if not defined PY (
  where python3 >nul 2>&1
  if not errorlevel 1 set "PY=python3"
)
if not defined PY (
  echo 未找到 python。请先从 https://www.python.org/downloads/ 安装 Python 3.10+，安装时勾选 Add python.exe to PATH。
  echo 或先双击「首次安装依赖.bat」。
  pause
  exit /b 1
)

%PY% -c "import openai, httpx" 2>nul
if errorlevel 1 (
  echo 依赖未安装。请先双击「首次安装依赖.bat」，完成后再启动。
  pause
  exit /b 1
)

if not exist userdata\diagrams mkdir userdata\diagrams
if not exist userdata\logs mkdir userdata\logs
%PY% desktop\app.py
if errorlevel 1 pause
