@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Virtual environment not found. Run install.bat first.
  pause
  exit /b 1
)

where npm.cmd >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js/npm not found. Node.js 20 or newer is required.
  pause
  exit /b 1
)
where node.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js not found. Node.js 20 or newer is required.
  pause
  exit /b 1
)
node.exe -e "process.exit(Number(process.versions.node.split('.')[0]) >= 20 ? 0 : 1)"
if errorlevel 1 (
  echo [ERROR] Node.js is too old. Node.js 20 or newer is required.
  node.exe --version
  pause
  exit /b 1
)

if not exist "prototype\node_modules\.bin\vite.cmd" (
  echo Installing locked frontend dependencies...
  call npm.cmd --prefix prototype ci
  if errorlevel 1 goto :err
)

echo Building offline frontend...
call npm.cmd --prefix prototype run build
if errorlevel 1 goto :err

echo Installing/verifying packaging tools...
"%PY%" -m pip install -r build-requirements.txt
if errorlevel 1 goto :err

echo Building Windows packages...
"%PY%" scripts\package_windows.py
if errorlevel 1 goto :err

echo.
echo Build complete. See dist\installer for the setup package.
pause
exit /b 0

:err
echo.
echo [ERROR] Build failed. Review the log above.
pause
exit /b 1
