@echo off
chcp 65001 >nul
echo 🚀 同步上游仓库更新...
echo.

REM 获取上游更新
echo 🔄 获取上游仓库更新...
git fetch upstream
if %errorlevel% neq 0 (
    echo ❌ 获取上游更新失败
    pause
    exit /b 1
)

REM 保存当前分支
for /f "tokens=*" %%i in ('git branch --show-current') do set CURRENT_BRANCH=%%i
echo 📍 当前分支: %CURRENT_BRANCH%

REM 切换到main分支
echo 🔄 切换到main分支...
git checkout main
if %errorlevel% neq 0 (
    echo ❌ 切换到main分支失败
    pause
    exit /b 1
)

REM 合并上游更新
echo 🔄 合并上游main分支更新...
git merge upstream/main
if %errorlevel% neq 0 (
    echo ❌ 合并上游更新失败，可能有冲突需要手动解决
    pause
    exit /b 1
)

REM 推送到你的fork
echo 🔄 推送更新到你的fork...
git push origin main
if %errorlevel% neq 0 (
    echo ❌ 推送失败
    pause
    exit /b 1
)

REM 切换回原分支
if not "%CURRENT_BRANCH%"=="main" (
    echo 🔄 切换回%CURRENT_BRANCH%分支...
    git checkout %CURRENT_BRANCH%
)

echo.
echo 🎉 同步完成！
echo.
echo 📋 接下来你可能需要:
echo 1. 检查是否有冲突需要解决
echo 2. 将main分支的更新合并到你的开发分支:
echo    git merge main
echo 3. 推送你的开发分支:
echo    git push origin %CURRENT_BRANCH%
echo.
pause