@echo off
chcp 65001 >nul
cd /d "C:\Users\33185\Desktop\企业\workmind7\server-py"

echo ========================================
echo  启动 WorkMind Python 后端
echo ========================================
echo.
echo 地址: http://localhost:3000
echo 健康检查: http://localhost:3000/health/live
echo.
echo 按 Ctrl+C 停止服务
echo ========================================

.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 3000