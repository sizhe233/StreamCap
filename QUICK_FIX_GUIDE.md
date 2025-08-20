# 自定义流大量断流问题 - 快速修复指南

## 🚨 紧急修复步骤

### 1. **立即降低并发数**
在 `config/user_settings.json` 中添加或修改：
```json
{
  "max_concurrent_custom_streams": 4
}
```

### 2. **增加重连缓冲时间**
```json
{
  "custom_stream_buffer_time": 120,
  "custom_stream_retry_interval": 15
}
```

### 3. **重启应用**
重启StreamCap应用以应用新配置。

## 🔧 根据系统配置调整

### 低配置系统 (4GB RAM以下)
```json
{
  "max_concurrent_custom_streams": 2,
  "custom_stream_buffer_time": 180,
  "custom_stream_retry_interval": 20
}
```

### 中等配置系统 (4-8GB RAM)
```json
{
  "max_concurrent_custom_streams": 4,
  "custom_stream_buffer_time": 90,
  "custom_stream_retry_interval": 15
}
```

### 高配置系统 (8GB+ RAM)
```json
{
  "max_concurrent_custom_streams": 8,
  "custom_stream_buffer_time": 60,
  "custom_stream_retry_interval": 10
}
```

## 📊 效果验证

### 1. **检查日志**
观察是否还有大量断流日志：
```
[INFO] 自定义流断流检测，开始XX秒缓冲等待期
[INFO] 自定义流重连成功，继续录制
```

### 2. **监控系统资源**
- CPU使用率应该 < 80%
- 内存使用率应该 < 85%
- 网络连接数应该稳定

### 3. **录制成功率**
- 新添加的任务应该能稳定录制
- 重连成功率应该 > 80%

## 🎯 长期优化建议

1. **逐步增加并发数**：系统稳定后，可以逐步增加并发数测试
2. **监控网络质量**：使用网络监控工具检查带宽和延迟
3. **定期清理**：定期清理临时文件和日志
4. **硬件升级**：考虑升级内存和CPU以支持更多并发

## ⚠️ 注意事项

- 修改配置后必须重启应用
- 建议在低峰期进行配置调整
- 保留原配置文件备份
- 逐步调整参数，避免一次性大幅修改

通过以上快速修复步骤，应该能够显著减少自定义流的断流问题。