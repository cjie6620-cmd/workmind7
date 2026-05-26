@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 安装中间件依赖...
.venv\Scripts\pip.exe install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
if %errorlevel% neq 0 (
    echo 安装失败！
    pause
    exit /b 1
)

echo.
echo 安装完成！启动命令：
echo .venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload
pause
