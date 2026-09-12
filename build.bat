@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [错误] 未找到虚拟环境，请先运行 install.bat。
  pause
  exit /b 1
)

rem Resolve Tcl/Tk from the base Python installation behind this virtual environment.
set "PYBASE="
set "PYBASE_FILE=%TEMP%\ddnovel_pybase_%RANDOM%_%RANDOM%.tmp"
"%PY%" -c "import sys; print(sys.base_prefix)" > "%PYBASE_FILE%"
if errorlevel 1 goto :err
set /p "PYBASE="<"%PYBASE_FILE%"
del /q "%PYBASE_FILE%" >nul 2>&1
set "PYBASE_FILE="
set "TCL_LIBRARY="
set "TK_LIBRARY="
if exist "%PYBASE%\tcl\tcl8.6\init.tcl" (
  if exist "%PYBASE%\tcl\tk8.6\tk.tcl" (
    set "TCL_LIBRARY=%PYBASE%\tcl\tcl8.6"
    set "TK_LIBRARY=%PYBASE%\tcl\tk8.6"
  )
)

echo 正在打包独立 exe（约需 1-3 分钟）...
"%PY%" -m PyInstaller --clean "多多朗读.spec"
if errorlevel 1 goto :err

echo.
echo 打包完成：dist\多多朗读.exe
pause
exit /b 0

:err
if defined PYBASE_FILE if exist "%PYBASE_FILE%" del /q "%PYBASE_FILE%" >nul 2>&1
echo.
echo [错误] 打包失败，请检查上方日志。
pause
exit /b 1
