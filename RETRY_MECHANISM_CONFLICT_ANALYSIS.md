# 重试机制冲突分析与解决方案

## 发现的冲突问题

### 1. **多层重试机制重叠**

项目中存在三层重试机制：

#### 第一层：FFmpeg内置重连机制
```python
# 在 ffmpeg_builders/base.py 中
"-reconnect_delay_max", "60",      # 最大重连延迟60秒
"-reconnect_streamed",             # 启用流重连
"-reconnect_at_eof",              # 在文件结束时重连
```

#### 第二层：DirectStreamDownloader原有重试机制
```python
# 原有参数
self.max_retries = max_retries        # 默认3次
self.retry_delay = retry_delay        # 默认5秒
self.current_retry = 0               # 重试计数器
```

#### 第三层：新增的自定义流重连机制
```python
# 新增参数
self.custom_stream_buffer_time = 60   # 缓冲时间60秒
self.custom_stream_retry_interval = 10 # 重连间隔10秒
```

### 2. **具体冲突点**

1. **变量冲突**：
   - 原实现中错误地使用了 `self.current_retry` 计数器
   - 这个变量属于原有的重试机制，会导致逻辑混乱

2. **重试逻辑冲突**：
   - 原有机制：基于次数限制（max_retries）
   - 新机制：基于时间限制（buffer_time）
   - 两者混用会导致不可预期的行为

3. **适用场景冲突**：
   - FFmpeg重连：适用于FFmpeg录制的流
   - DirectDownloader重试：适用于HTTP下载
   - 自定义流重连：专门针对FLV/M3U8格式

## 解决方案

### 1. **机制分离**

#### 完全分离三套重试机制：

```python
class DirectStreamDownloader:
    def __init__(self, ...):
        # 原有机制（用于常规流）
        self.max_retries = max_retries
        self.retry_delay = retry_delay  
        self.current_retry = 0
        
        # 自定义流专用机制
        self.custom_stream_buffer_time = custom_stream_buffer_time
        self.custom_stream_retry_interval = custom_stream_retry_interval
        self.custom_retry_count = 0  # 独立计数器
        self.disconnect_start_time = None
```

#### 路由逻辑：

```python
async def _download_stream(self):
    if self.is_custom_stream:
        await self._download_custom_stream()  # 使用自定义流机制
    else:
        await self._download_regular_stream()  # 使用原有机制
```

### 2. **机制选择策略**

| 流类型 | 使用的重试机制 | 适用场景 |
|--------|---------------|----------|
| FFmpeg录制 | FFmpeg内置重连 | 大部分平台直播流 |
| 常规HTTP流 | DirectDownloader原有重试 | 简单HTTP流下载 |
| 自定义流(FLV/M3U8) | 新的断流重连策略 | 用户提供的自定义流URL |

### 3. **参数隔离**

#### 原有参数（保持不变）：
- `max_retries`: 常规流最大重试次数
- `retry_delay`: 常规流重试延迟
- `current_retry`: 常规流重试计数器

#### 新增参数（完全独立）：
- `custom_stream_buffer_time`: 自定义流缓冲时间
- `custom_stream_retry_interval`: 自定义流重连间隔
- `custom_retry_count`: 自定义流重连计数器
- `disconnect_start_time`: 断流开始时间

### 4. **日志区分**

```python
# 常规流重试日志
logger.info(f"尝试重连直播流 (第{self.current_retry}/{self.max_retries}次)")

# 自定义流重连日志  
logger.info(f"自定义流重连尝试 (第{self.custom_retry_count}次)")
```

## 修复后的优势

### 1. **清晰的职责分离**
- 每种流类型使用最适合的重试策略
- 避免参数和逻辑混乱
- 便于维护和调试

### 2. **向后兼容**
- 原有功能完全不受影响
- 常规流继续使用原有的重试机制
- FFmpeg录制继续使用内置重连

### 3. **灵活配置**
- 用户可以针对不同场景调整参数
- 自定义流可以使用更长的缓冲时间
- 常规流保持快速失败策略

### 4. **更好的用户体验**
- 自定义流：长时间缓冲，适合不稳定的流
- 常规流：快速重试，适合临时网络问题
- FFmpeg流：内置重连，适合大部分直播平台

## 测试建议

### 1. **分别测试三种场景**
```python
# 测试1: 常规HTTP流
url = "http://example.com/stream"  # 不包含.flv/.m3u8

# 测试2: 自定义FLV流  
url = "http://example.com/stream.flv"

# 测试3: 自定义M3U8流
url = "http://example.com/stream.m3u8"
```

### 2. **验证重试行为**
- 常规流：应该在3次重试后停止
- 自定义流：应该在60秒内持续重试
- FFmpeg流：应该使用FFmpeg内置重连

### 3. **检查日志输出**
- 确保使用正确的日志前缀
- 验证计数器独立工作
- 确认超时行为正确

## 总结

通过完全分离三套重试机制，我们解决了：
- ✅ 变量冲突问题
- ✅ 逻辑混乱问题  
- ✅ 适用场景冲突
- ✅ 向后兼容性问题

现在每种流类型都有最适合的重试策略，提供了更好的稳定性和用户体验。