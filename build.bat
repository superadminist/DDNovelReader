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

where npm.cmd >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 Node.js/npm。源码打包需要 Node.js 20 或更高版本。
  pause
  exit /b 1
)
where node.exe >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 Node.js。源码打包需要 Node.js 20 或更高版本。
  pause
  exit /b 1
)
node.exe -e "process.exit(Number(process.versions.node.split('.')[0]) >= 20 ? 0 : 1)"
if errorlevel 1 (
  echo [错误] 当前 Node.js 版本过旧。源码打包需要 Node.js 20 或更高版本。
  node.exe --version
  pause
  exit /b 1
)

if not exist "prototype\node_modules\.bin\vite.cmd" (
  echo 正在安装前端锁定依赖...
  call npm.cmd --prefix prototype ci
  if errorlevel 1 goto :err
)

echo 正在构建离线前端...
call npm.cmd --prefix prototype run build
if errorlevel 1 goto :err

echo 正在安装/校验打包工具...
"%PY%" -m pip install -r build-requirements.txt
if errorlevel 1 goto :err

for /f "usebackq delims=" %%I in (`"%PY%" -c "import sys; print(sys.base_prefix)"`) do set "PYBASE=%%I"
if not defined PYBASE goto :err
rem Freeze from a deterministic DLL search path. Development shells may inject
rem unrelated Poppler/libheif UCRT shims that make Qt fail after packaging.
set "PATH="
set "Path="
set "Path=%~dp0.venv\Scripts;%PYBASE%;%PYBASE%\Scripts;%SystemRoot%\System32;%SystemRoot%"

echo 正在打包独立 exe（约需 1-3 分钟）...
"%PY%" -m PyInstaller --clean --noconfirm "多多朗读.spec"
if errorlevel 1 goto :err

echo.
echo 打包完成：dist\多多朗读.exe
pause
exit /b 0

:err
echo.
echo [错误] 打包失败，请检查上方日志。
pause
exit /b 1
