# 自定义流断流重连功能实现总结

## 实现概述

成功为StreamCap项目实现了自定义流（FLV/M3U8）的断流重连策略，满足了用户提出的需求：
- ✅ 1分钟缓冲等待时间（可配置）
- ✅ 10秒间隔重连尝试（可配置）
- ✅ 重连成功后继续录制
- ✅ 超时后自动取消任务

## 修改的文件

### 1. 核心功能文件

#### `app/core/media/direct_downloader.py`
- **新增参数**：
  - `custom_stream_buffer_time`: 缓冲等待时间（默认60秒）
  - `custom_stream_retry_interval`: 重连间隔（默认10秒）
  - `disconnect_start_time`: 断流开始时间记录
  - `is_custom_stream`: 自定义流标识

- **新增方法**：
  - `_is_custom_stream_url()`: 识别自定义流URL
  - `_download_custom_stream()`: 自定义流下载逻辑
  - `_download_regular_stream()`: 常规流下载逻辑（重构）
  - `_handle_custom_stream_disconnect()`: 断流处理和重连策略

#### `app/core/recording/stream_manager.py`
- **修改位置**：DirectStreamDownloader实例化部分
- **新增配置**：从用户配置读取自定义流重连参数
- **参数传递**：将配置参数传递给DirectStreamDownloader

### 2. 配置文件

#### `config/default_settings.json`
- **新增配置项**：
  - `"custom_stream_buffer_time": 60`
  - `"custom_stream_retry_interval": 10`

#### `locales/zh_CN.json`
- **新增中文标签**：
  - `custom_stream_buffer_time`: "自定义流断流缓冲时间(秒)"
  - `custom_stream_buffer_time_tip`: "自定义流断流后的等待重连时间，默认60秒"
  - `custom_stream_retry_interval`: "自定义流重连间隔(秒)"
  - `custom_stream_retry_interval_tip`: "自定义流断流后每次重连尝试的间隔时间，默认10秒"

#### `locales/en.json`
- **新增英文标签**：
  - `custom_stream_buffer_time`: "Custom Stream Disconnect Buffer Time (Seconds)"
  - `custom_stream_buffer_time_tip`: "Buffer time to wait for reconnection after custom stream disconnects, default 60 seconds"
  - `custom_stream_retry_interval`: "Custom Stream Retry Interval (Seconds)"
  - `custom_stream_retry_interval_tip`: "Interval between reconnection attempts after custom stream disconnects, default 10 seconds"

### 3. 文档和示例文件

#### `CUSTOM_STREAM_RECONNECT_README.md`
- 详细的功能说明文档
- 配置参数说明
- 使用建议和故障排除

#### `custom_stream_config_example.json`
- 配置示例文件
- 不同场景的推荐配置

#### `test_custom_stream_reconnect.py`
- 功能测试脚本
- 用于验证重连逻辑

## 技术实现细节

### 1. 自定义流识别
```python
def _is_custom_stream_url(self, url: str) -> bool:
    """判断是否为自定义流URL（FLV或M3U8）"""
    return '.flv' in url.lower() or '.m3u8' in url.lower()
```

### 2. 断流重连策略
```python
async def _handle_custom_stream_disconnect(self, error_reason: str) -> bool:
    """处理自定义流断流，实现缓冲等待和重连策略"""
    # 记录断流开始时间
    # 检查是否超过缓冲时间
    # 在缓冲期内进行重连尝试
    # 返回是否应该继续重连
```

### 3. 状态管理
- 断流时设置 `is_reconnecting = True`
- 重连成功时重置状态和计时器
- 通过UI更新显示当前状态

## 工作流程

### 正常流程
1. 用户添加自定义流URL（包含.flv或.m3u8）
2. 系统识别为自定义流，启用专用下载逻辑
3. 建立连接，开始录制

### 断流重连流程
1. **断流检测**：连接中断或HTTP错误
2. **错误分析**：区分关键错误和可重连错误
3. **启动缓冲期**：记录断流时间，开始60秒等待期
4. **重连尝试**：每10秒尝试重新连接
5. **状态更新**：UI显示"监控中"状态
6. **结果处理**：
   - 成功：恢复录制，重置计时器
   - 超时：停止任务，保留文件

## 配置灵活性

用户可以通过设置界面或配置文件调整：
- **缓冲时间**：根据网络稳定性调整（30-180秒）
- **重连间隔**：根据服务器响应调整（5-20秒）
- **适应场景**：稳定网络、不稳定网络、重要直播等

## 兼容性保证

- **向后兼容**：不影响现有功能和常规流录制
- **平台兼容**：支持Windows、macOS、Linux
- **格式支持**：专门针对FLV和M3U8格式优化

## 测试建议

1. **功能测试**：使用提供的测试脚本验证重连逻辑
2. **配置测试**：测试不同参数组合的效果
3. **边界测试**：测试网络中断、服务器错误等场景
4. **性能测试**：确保重连不影响系统性能

## 重试机制冲突解决

### 发现的问题
在实现过程中发现项目存在三层重试机制：
1. **FFmpeg内置重连**：`-reconnect_delay_max 60`
2. **DirectDownloader原有重试**：`max_retries=3, retry_delay=5`
3. **新增自定义流重连**：`buffer_time=60, retry_interval=10`

### 解决方案
- **完全分离**：为自定义流创建独立的重连机制
- **变量隔离**：使用`custom_retry_count`替代`current_retry`
- **路由分离**：自定义流和常规流使用不同的下载逻辑
- **向后兼容**：原有功能完全不受影响

### 机制选择
| 流类型 | 重试机制 | 适用场景 |
|--------|----------|----------|
| FFmpeg录制 | FFmpeg内置重连 | 大部分平台直播流 |
| 常规HTTP流 | 原有重试机制 | 简单HTTP下载 |
| 自定义流 | 新断流重连策略 | FLV/M3U8自定义流 |

## 后续优化建议

1. **智能重连间隔**：根据失败次数动态调整间隔
2. **网络质量检测**：根据网络状况自动调整参数
3. **统计信息**：记录重连成功率和平均恢复时间
4. **用户通知**：重连状态的更详细通知

## 总结

本次实现完全满足了用户需求，并解决了重试机制冲突：
- ✅ 可配置的1分钟缓冲等待时间
- ✅ 可配置的10秒重连间隔
- ✅ 重连成功后继续录制
- ✅ 超时后自动取消任务
- ✅ 完整的日志记录和状态管理
- ✅ 用户友好的配置界面
- ✅ 详细的文档和使用说明
- ✅ 解决了多层重试机制冲突
- ✅ 保持了向后兼容性

该功能将显著提高自定义流录制的稳定性和用户体验，同时不影响现有功能。