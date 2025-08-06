@echo off
chcp 65001 >nul
echo 正在查找占用端口 8000 的进程...
echo.

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    if not "%%a"=="0" (
        echo 发现进程 PID: %%a 占用端口 8000
        echo 正在终止进程...
        taskkill /PID %%a /F >nul 2>&1
        if !errorlevel! equ 0 (
            echo 成功终止进程 %%a
        ) else (
            echo 终止进程 %%a 失败，可能需要管理员权限
        )
    )
)

echo.
echo 检查端口 8000 当前状态:
netstat -ano | findstr :8000

echo.
echo 完成！现在可以重新启动 FastAPI 服务器了。
pause