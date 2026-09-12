@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [错误] 未找到虚拟环境 Python，请先运行 install.bat。
  pause
  exit /b 1
)

rem novelreader\main.py discovers Tcl/Tk from the base Python installation.
rem A standard Windows venv does not copy the Tcl/Tk script libraries.

echo 正在启动多多朗读...
"%PY%" "%~dp0novelreader\main.py"
if errorlevel 1 (
  echo.
  echo [错误] 程序异常退出，请查看上方提示。
  pause
)
endlocal
