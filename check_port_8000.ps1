# 检查端口 8000 状态的 PowerShell 脚本

Write-Host "检查端口 8000 的详细状态..." -ForegroundColor Yellow
Write-Host "=" * 50

# 检查 TCP 连接
Write-Host "`n[TCP 连接状态]" -ForegroundColor Cyan
$tcpConnections = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue

if ($tcpConnections) {
    foreach ($conn in $tcpConnections) {
        $processId = $conn.OwningProcess
        $processName = ""
        
        if ($processId -gt 0) {
            $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
            if ($process) {
                $processName = $process.ProcessName
            }
        }
        
        Write-Host "  地址: $($conn.LocalAddress):$($conn.LocalPort)" -ForegroundColor White
        Write-Host "  状态: $($conn.State)" -ForegroundColor $(if ($conn.State -eq "Listen") { "Red" } else { "Green" })
        Write-Host "  进程: $processId $(if ($processName) { "($processName)" })" -ForegroundColor White
        Write-Host "  远程: $($conn.RemoteAddress):$($conn.RemotePort)" -ForegroundColor Gray
        Write-Host ""
    }
} else {
    Write-Host "  没有发现 TCP 连接占用端口 8000" -ForegroundColor Green
}

Write-Host "`n✅ 端口检查完成！" -ForegroundColor Green
Write-Host "现在可以访问以下地址查看 API 文档：" -ForegroundColor Yellow
Write-Host "  📖 Swagger UI: http://127.0.0.1:8000/docs" -ForegroundColor Cyan
Write-Host "  📋 ReDoc: http://127.0.0.1:8000/redoc" -ForegroundColor Cyan

Write-Host "`n按任意键退出..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")