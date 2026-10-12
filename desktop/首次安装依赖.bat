chcp 65001 >nul
@echo off
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"
if exist "requirements.txt" if exist "desktop\app.py" goto :have_root
if exist "..\requirements.txt" cd /d "%~dp0.."
if exist "..\archgen.py" if not exist "desktop\app.py" cd /d "%~dp0.."
if not exist "desktop\app.py" (
  echo 找不到 ArchGen 目录结构。
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
  echo 未找到 python。请先从 https://www.python.org/downloads/ 安装 Python 3.10 或更高版本，安装时勾选 Add python.exe to PATH。
  pause
  exit /b 1
)

if not exist "%ROOT%\requirements.txt" (
  echo 找不到 requirements.txt：%ROOT%\requirements.txt
  pause
  exit /b 1
)

echo ^>^>^> 目录：%ROOT%
%PY% --version
echo ^>^>^> 安装依赖…
%PY% -m pip install -r "%ROOT%\requirements.txt"
if errorlevel 1 (
  echo pip 安装失败。
  pause
  exit /b 1
)
echo ^>^>^> 安装截图浏览器 Chromium…
%PY% -m playwright install chromium
if errorlevel 1 (
  echo Playwright Chromium 安装失败。
  pause
  exit /b 1
)

if not exist userdata\diagrams mkdir userdata\diagrams
if not exist userdata\logs mkdir userdata\logs
echo.
echo 安装完成。请双击「启动 ArchGen.bat」打开界面。
echo 请先安装 Chrome 或 Edge（出图需要）。不要在 Cursor 里启动，请用系统「命令提示符」或双击本目录的 bat。
echo 若弹出 SmartScreen 蓝屏：点「更多信息 → 仍要运行」。
pause
