#!/usr/bin/env python3
"""
同步上游仓库更新的脚本
Sync upstream repository updates script
"""

import subprocess
import sys
import os

def run_command(command, description=""):
    """执行命令并处理错误"""
    print(f"🔄 {description}")
    print(f"执行命令: {command}")
    
    try:
        result = subprocess.run(command, shell=True, check=True, 
                              capture_output=True, text=True)
        if result.stdout:
            print(f"✅ {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 错误: {e}")
        if e.stderr:
            print(f"错误详情: {e.stderr.strip()}")
        return False

def sync_upstream():
    """同步上游仓库更新"""
    print("🚀 开始同步上游仓库更新...")
    
    # 检查是否在git仓库中
    if not os.path.exists('.git'):
        print("❌ 错误: 当前目录不是git仓库")
        return False
    
    # 获取当前分支
    try:
        current_branch = subprocess.check_output(
            "git branch --show-current", shell=True, text=True
        ).strip()
        print(f"📍 当前分支: {current_branch}")
    except subprocess.CalledProcessError:
        print("❌ 无法获取当前分支")
        return False
    
    # 步骤1: 获取上游更新
    if not run_command("git fetch upstream", "获取上游仓库更新"):
        return False
    
    # 步骤2: 切换到main分支
    if not run_command("git checkout main", "切换到main分支"):
        return False
    
    # 步骤3: 合并上游main分支
    if not run_command("git merge upstream/main", "合并上游main分支更新"):
        return False
    
    # 步骤4: 推送更新到你的fork
    if not run_command("git push origin main", "推送更新到你的fork"):
        return False
    
    # 步骤5: 切换回原来的分支
    if current_branch != "main":
        if not run_command(f"git checkout {current_branch}", f"切换回{current_branch}分支"):
            return False
    
    print("🎉 同步完成！")
    print("\n📋 接下来你可能需要:")
    print("1. 检查是否有冲突需要解决")
    print("2. 将main分支的更新合并到你的开发分支:")
    print(f"   git merge main  # 在{current_branch}分支中执行")
    print("3. 推送你的开发分支:")
    print(f"   git push origin {current_branch}")
    
    return True

def show_status():
    """显示仓库状态"""
    print("📊 仓库状态信息:")
    
    # 显示远程仓库
    print("\n🔗 远程仓库:")
    run_command("git remote -v", "")
    
    # 显示分支信息
    print("\n🌿 本地分支:")
    run_command("git branch", "")
    
    # 显示最近提交
    print("\n📝 最近3次提交:")
    run_command("git log --oneline -3", "")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        show_status()
    else:
        sync_upstream()