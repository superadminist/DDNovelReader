@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo 正在创建 Python 虚拟环境...
python -m venv .venv
if errorlevel 1 goto :err

echo 正在安装依赖...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :err

echo.
echo 运行依赖安装完成！请运行 run.bat 启动程序。
echo 如需打包，请安装 Node.js 20+ 后运行 build.bat。
pause
exit /b 0

:err
echo.
echo [错误] 安装失败，请检查网络后重试。
pause
exit /b 1
