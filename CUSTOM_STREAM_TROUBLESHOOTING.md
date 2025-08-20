# 自定义流大量断流问题排查与解决方案

## 🚨 问题现象

用户反馈在录制自定义流时，特别是通过FastAPI批量添加任务后，会出现大量任务莫名断流的情况。

## 🔍 根本原因分析

### 1. **并发连接限制**
- **服务器端限制**：目标服务器可能限制同一IP的并发连接数
- **客户端限制**：HTTP客户端默认连接池大小不足
- **网络设备限制**：路由器、防火墙等网络设备的连接数限制

### 2. **资源竞争**
- **内存不足**：大量并发任务消耗过多内存
- **文件句柄耗尽**：同时打开过多文件
- **CPU资源不足**：处理大量并发连接导致CPU过载

### 3. **网络拥塞**
- **带宽不足**：多个流同时下载超出网络带宽
- **DNS解析延迟**：大量并发请求导致DNS查询超时
- **TCP连接建立失败**：网络拥塞导致连接建立超时

## ✅ 解决方案

### 1. **HTTP连接池优化**

#### 实现共享HTTP客户端池
```python
class HTTPClientPool:
    # 配置适合大量并发的HTTP客户端
    limits = httpx.Limits(
        max_keepalive_connections=50,  # 保持连接数
        max_connections=100,           # 最大连接数
        keepalive_expiry=30.0         # 连接保持时间
    )
    
    timeout = httpx.Timeout(
        connect=10.0,    # 连接超时
        read=30.0,       # 读取超时
        write=10.0,      # 写入超时
        pool=5.0         # 连接池超时
    )
```

#### 优势
- **连接复用**：减少TCP连接建立开销
- **资源共享**：多个任务共享连接池
- **超时控制**：避免长时间等待

### 2. **并发控制机制**

#### 信号量限制并发数
```python
# 使用信号量控制最大并发连接数
semaphore = asyncio.Semaphore(max_concurrent_downloads)
async with semaphore:
    # 执行下载任务
```

#### 配置参数
- `max_concurrent_custom_streams`: 最大并发自定义流数（默认8）
- 可根据网络和硬件性能调整

### 3. **自适应重连策略**

#### 智能延迟调整
```python
# 根据连接失败次数动态调整重连延迟
if connection_failures > 3:
    adaptive_retry_delay = min(retry_interval * 2, 30)
elif connection_failures > 10:
    adaptive_retry_delay = min(retry_interval * 3, 60)
```

#### 连接稳定性监控
- 记录连接失败次数
- 监控最后成功连接时间
- 动态调整重连策略

### 4. **错误处理优化**

#### 区分错误类型
- **临时错误**：网络拥塞、超时等，可重试
- **永久错误**：404、403等，不应重试
- **系统错误**：资源不足等，需要降低并发

#### 优雅降级
- 检测到系统资源不足时自动降低并发数
- 网络拥塞时增加重连延迟
- 连接频繁失败时暂停新任务

## 📊 配置建议

### 1. **网络环境配置**

#### 高速稳定网络
```json
{
  "max_concurrent_custom_streams": 12,
  "custom_stream_buffer_time": 45,
  "custom_stream_retry_interval": 8
}
```

#### 一般网络环境
```json
{
  "max_concurrent_custom_streams": 8,
  "custom_stream_buffer_time": 60,
  "custom_stream_retry_interval": 10
}
```

#### 不稳定网络环境
```json
{
  "max_concurrent_custom_streams": 4,
  "custom_stream_buffer_time": 90,
  "custom_stream_retry_interval": 15
}
```

### 2. **硬件配置建议**

#### 内存要求
- **最低**：4GB RAM，建议并发数 ≤ 4
- **推荐**：8GB RAM，建议并发数 ≤ 8
- **高性能**：16GB+ RAM，建议并发数 ≤ 16

#### CPU要求
- **最低**：双核CPU，建议并发数 ≤ 4
- **推荐**：四核CPU，建议并发数 ≤ 8
- **高性能**：八核+ CPU，建议并发数 ≤ 16

## 🔧 故障排查步骤

### 1. **检查系统资源**
```bash
# 检查内存使用
free -h

# 检查CPU使用
top

# 检查网络连接数
netstat -an | grep ESTABLISHED | wc -l
```

### 2. **检查网络状况**
```bash
# 测试网络延迟
ping target-server.com

# 测试带宽
speedtest-cli

# 检查DNS解析
nslookup target-server.com
```

### 3. **分析日志**
```bash
# 查看断流相关日志
grep "断流\|重连\|失败" logs/app.log

# 统计错误类型
grep "HTTP" logs/app.log | sort | uniq -c
```

### 4. **逐步调试**
1. **单任务测试**：先测试单个自定义流是否稳定
2. **小批量测试**：逐步增加并发数，找到稳定的上限
3. **长时间测试**：运行24小时以上，观察稳定性
4. **压力测试**：在高负载下测试系统表现

## 📈 监控指标

### 1. **连接指标**
- 并发连接数
- 连接成功率
- 平均连接时间
- 重连频率

### 2. **性能指标**
- CPU使用率
- 内存使用率
- 网络带宽使用
- 磁盘I/O

### 3. **业务指标**
- 录制成功率
- 平均录制时长
- 断流恢复时间
- 文件完整性

## 🚀 性能优化建议

### 1. **系统级优化**
```bash
# 增加文件句柄限制
ulimit -n 65536

# 优化TCP参数
echo 'net.core.somaxconn = 65535' >> /etc/sysctl.conf
echo 'net.ipv4.tcp_max_syn_backlog = 65535' >> /etc/sysctl.conf
```

### 2. **应用级优化**
- 使用异步I/O减少阻塞
- 实现连接池复用
- 添加熔断机制
- 实现优雅降级

### 3. **网络级优化**
- 使用CDN加速
- 配置负载均衡
- 优化DNS解析
- 使用HTTP/2（如果支持）

## 📋 最佳实践

### 1. **任务管理**
- 分批添加任务，避免瞬间大量并发
- 监控系统资源，动态调整并发数
- 实现任务队列，平滑处理请求

### 2. **错误处理**
- 记录详细的错误日志
- 实现智能重试机制
- 提供用户友好的错误提示

### 3. **资源管理**
- 及时释放不用的连接
- 定期清理临时文件
- 监控内存泄漏

### 4. **用户体验**
- 提供实时状态更新
- 显示详细的进度信息
- 支持手动重试失败任务

通过以上优化措施，可以显著减少自定义流的断流问题，提高录制的稳定性和成功率。