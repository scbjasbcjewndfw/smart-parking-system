@echo off
chcp 65001 >nul
setlocal

rem ============================================================
rem  停车车牌识别系统 —— 一键启动开发环境
rem  后端 Flask : 5001（5000 常被本机其他项目占用）
rem  前端 Vite  : 5174（5173 常被本机其他项目占用）
rem ============================================================

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend\car_project"
set "FRONTEND=%ROOT%frontend"

if not exist "%BACKEND%\.venv\Scripts\python.exe" (
    echo [错误] 未找到后端虚拟环境：%BACKEND%\.venv
    echo         请先执行：python -m venv .venv 并安装 requirements.txt
    pause
    exit /b 1
)

if not exist "%FRONTEND%\node_modules" (
    echo [错误] 未找到前端依赖：%FRONTEND%\node_modules
    echo         请先执行：cd frontend ^&^& npm install
    pause
    exit /b 1
)

echo 正在启动后端（端口 5001）...
start "carpark-backend" cmd /k "cd /d %BACKEND% && .venv\Scripts\python.exe app.py"

echo 正在启动前端（端口 5174）...
start "carpark-frontend" cmd /k "cd /d %FRONTEND% && npm run dev"

echo.
echo 已启动。服务就绪后访问： http://127.0.0.1:5174
echo 后端首次启动需加载 torch/paddle，约 15-25 秒；前端在浏览器里能打开即可用。
echo 关闭方式：直接关掉弹出的两个命令行窗口。
echo.
pause
