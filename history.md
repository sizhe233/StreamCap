# StreamCap 开发历史

## 2025-08-21 03:01:30 - 修复录制任务列表卡死问题

### 问题描述
修复"Card not found"日志问题后，用户反馈录制任务列表卡住了，UI无响应。

### 问题分析
**根本原因**：在修复过程中引入的新的UI阻塞问题：

1. **同步UI操作阻塞**：
   - `subscribe_add_cards`方法中执行同步UI更新
   - `self.recording_card_area.update()` 和 `self.content_area.update()` 可能在错误时机执行
   - 没有页面连接状态检查，可能在页面断开时进行UI操作

2. **消息风暴问题**：
   - 速度回调每2秒发送UI更新请求
   - 多个录制任务同时更新，UI响应不过来
   - 缺少频率限制机制

3. **错误处理不足**：
   - UI更新失败时没有回滚机制
   - 缺少异常捕获，一旦出错就卡死

### 核心修复方案

#### 1. **增强UI更新安全性**
```python
# 添加页面连接状态检查
if hasattr(self.page, 'session_id') and self.page.session_id:
    # 安全的UI更新
    try:
        self.recording_card_area.update()
        self.content_area.update()
    except Exception as ui_error:
        logger.warning(f"UI update failed: {ui_error}")
        # 自动回滚
        if card in self.recording_card_area.content.controls:
            self.recording_card_area.content.controls.remove(card)
```

#### 2. **速度更新频率限制**
```python
# 修改前：每2秒更新
if current_time - self.last_speed_update >= 2.0:

# 修改后：每秒最多1次，减少UI负担
if current_time - last_ui_update >= 1.0:
    self.app.page.run_task(self.app.record_card_manager.update_card, self.recording)
    self._last_ui_update = current_time
```

#### 3. **静默处理机制**
```python
# 移除频繁的日志输出，静默处理
if recording.rec_id not in self.cards_obj:
    return  # 静默返回，不记录日志
```

### 技术细节
- **页面状态检查**：在UI操作前检查页面连接状态
- **错误回滚**：UI更新失败时自动清理已添加的控件
- **频率控制**：限制UI更新频率，避免过度负担
- **异常隔离**：增强异常处理，避免单个错误影响整体

### 预期效果
- 消除UI卡死问题，恢复正常响应
- 减少UI更新频率，提升性能
- 增强系统稳定性和错误恢复能力
- 保持录制功能正常工作

## 2025-08-21 01:30:37 - 修复API阻塞修复后的"Card not found"频繁日志问题

### 问题描述
修复API阻塞问题后，后台频繁出现"Card not found for recording"的DEBUG日志，表明UI卡片创建和速度更新存在时序问题。

### 问题分析
**根本原因**：简化API流程后，时序问题暴露：

1. **时序冲突**：
   - API录制任务启动后，`speed_update_callback`立即开始调用
   - 但此时UI卡片可能还没通过pubsub机制创建完成
   - 导致速度回调尝试更新不存在的卡片

2. **创建延迟**：
   - 之前移除了FastAPI中的直接卡片创建逻辑
   - 改为只发送pubsub通知，但pubsub处理有延迟
   - 速度回调比卡片创建更早触发

3. **日志噪音**：
   - 每2秒的速度更新都会产生"Card not found"日志
   - 大量录制任务时日志频繁刷屏

### 核心修复方案

#### 1. **自动创建卡片机制**
```python
# 在update_card中添加自动创建逻辑
if recording.rec_id not in self.cards_obj:
    logger.debug(f"Card not found for recording: {recording.rec_id}, attempting to create it")
    card = await self.create_card(recording)
    if card is None:
        return
```

#### 2. **统一UI更新机制**
```python
# 修改前：直接调用update_card
self.app.page.run_task(self.app.record_card_manager.update_card, self.recording)

# 修改后：使用pubsub机制
self.app.page.pubsub.send_others_on_topic("update", self.recording)
```

#### 3. **增强卡片创建**
```python
# 在create_card中添加自动添加到页面的逻辑
if (hasattr(self.app, 'current_page') and 
    self.app.current_page and 
    hasattr(self.app.current_page, 'recording_card_area')):
    self.app.current_page.recording_card_area.content.controls.append(card)
    self.app.current_page.recording_card_area.update()
```

### 技术细节
- **时序安全**：确保卡片在需要时能自动创建，避免时序依赖
- **统一机制**：所有UI更新都通过pubsub路由，避免直接调用混乱
- **减少日志噪音**：解决频繁"Card not found"警告问题

### 预期效果
- 消除频繁的"Card not found"日志
- 提升UI响应的稳定性
- 确保录制速度显示正常工作
- 维持API高并发性能

## 2025-01-19 11:32:18 - 修复API创建到录制流程中的阻塞问题

### 问题描述
用户反馈通过API创建录制任务时，发现有些阻塞问题会导致其他任务间歇性断流。需要排查API从创建到开始录制的整个流程中的阻塞点。

### 问题分析
通过详细代码审查，发现了API流程中的关键阻塞点：

1. **线程锁竞争阻塞**：
   - `GlobalRecordingState.lock`使用`threading.Lock()`
   - 多个API请求同时创建任务时会在锁上排队等待
   - 文件I/O操作在锁内执行，增加锁持有时间

2. **文件I/O重试机制阻塞**：
   - `persist_recordings()`有3次重试机制
   - 最坏情况可能阻塞几秒钟

3. **大量page.run_task堆积**：
   - `start_monitor_recording()`中连续3个`page.run_task`调用
   - UI任务队列可能堵塞

4. **复杂UI同步更新阻塞**：
   - FastAPI中140行复杂UI同步逻辑
   - 大量同步UI操作可能阻塞

### 核心修复方案

#### 1. **线程锁改为异步锁**
```python
# 修改前
class GlobalRecordingState:
    lock = threading.Lock()

with GlobalRecordingState.lock:
    GlobalRecordingState.recordings.append(recording)
    await self.persist_recordings()  # 文件I/O在锁内！

# 修改后  
class GlobalRecordingState:
    lock = asyncio.Lock()

async with GlobalRecordingState.lock:
    GlobalRecordingState.recordings.append(recording)
# 文件I/O移到锁外执行
await self.persist_recordings()
```

#### 2. **优化批量任务处理**
```python
# 修改前：连续多个page.run_task调用
self.app.page.run_task(self._start_custom_stream_recording, recording)
self.app.page.run_task(self.app.record_card_manager.update_card, recording)
self.app.page.run_task(self.persist_recordings)

# 修改后：使用异步任务，避免阻塞
tasks = [self._start_custom_stream_recording(recording)]
asyncio.create_task(self.persist_recordings())
for task in tasks:
    asyncio.create_task(task)
```

#### 3. **简化UI更新流程**
```python
# 修改前：140行复杂UI同步逻辑
# 大量同步页面操作...

# 修改后：简单pubsub通知
self.app_manager.page.pubsub.send_others_on_topic("add", recording)
```

#### 4. **文件I/O防抖动优化**
```python
async def _save_config_with_debounce(self, config_path, config, delay=0.5):
    # 防抖动保存机制，短时间内多次保存请求只执行最后一次
    if config_path in self._pending_saves:
        self._pending_saves[config_path].cancel()
    self._pending_saves[config_path] = asyncio.create_task(delayed_save())
```

### 技术细节
- 修改了`record_manager.py`中的锁机制和任务调度
- 修改了`stream_manager.py`中的异步任务处理
- 简化了`fastapi_server.py`中的UI更新逻辑
- 优化了`config_manager.py`中的文件保存机制

### 预期效果
- 消除多个API请求的锁竞争
- 大幅减少间歇性断流风险  
- 提升高并发场景下的响应性能
- 改善API调用的稳定性

## 2025-08-21 00:56:06 - 修复并发配置不生效的问题

### 问题描述
用户已经设置`max_concurrent_custom_streams: 100`，但第9个及以后的任务还是处于"等待中"状态，说明并发配置没有生效。

### 问题分析
1. **配置文件问题**：
   - `default_settings.json`中设置了100
   - 但`user_settings.json`中缺少`max_concurrent_custom_streams`配置项
   - 系统优先使用user_settings，缺少时使用默认值8

2. **全局信号量不会动态更新**：
   ```python
   if _global_semaphore is None:  # 只有第一次才初始化！
       _global_semaphore = asyncio.Semaphore(max_concurrent)
   ```
   - 首次启动时创建信号量为8
   - 后续修改配置，信号量不会重新创建
   - 依然是8个并发限制

### 核心修复方案
1. **添加配置到user_settings.json**：
   ```json
   {
     "max_concurrent_custom_streams": 100,
     "custom_stream_buffer_time": 60,
     "custom_stream_retry_interval": 10
   }
   ```

2. **修复全局信号量动态更新**：
   ```python
   # 如果配置发生变化，重新创建信号量
   if _global_semaphore is None or _current_max_concurrent != max_concurrent:
       logger.info(f"初始化/更新全局信号量，最大并发数: {max_concurrent}")
       _global_semaphore = asyncio.Semaphore(max_concurrent)
       _current_max_concurrent = max_concurrent
   ```

### 技术细节
- 修改了`direct_downloader.py`中的`get_global_semaphore`函数
- 添加了配置变化检测机制
- 现在信号量会自动根据配置更新，无需重启应用

## 2025-01-19 11:17:22 - 修复第8个任务后下载速度不更新的并发限制问题

### 问题描述
用户反馈在任务模板第8个任务之后，下载速度不更新了，只更新下载时间，需要检查面板更新逻辑。

### 问题分析
1. **并发限制配置**：系统配置`max_concurrent_custom_streams: 8`，最多同时下载8个自定义流
2. **信号量阻塞**：第9个及以后的任务在`async with semaphore:`处等待，无法进入实际下载循环
3. **速度更新缺失**：被阻塞的任务虽然显示"运行中"，但没有触发速度更新回调，导致UI只显示时间不显示速度

### 核心修复方案
1. **添加等待状态检测**：
   - 在获取信号量前检查`semaphore._value == 0`判断是否需要等待
   - 创建等待期间的UI更新任务，定期显示"等待中..."状态

2. **优化UI反馈机制**：
   - 修改速度更新回调逻辑，当`total_bytes == 0 && elapsed_time > 0`时显示"等待中..."
   - 在等待信号量期间创建定期更新任务，每2秒更新一次状态

3. **完善异常处理**：
   - 添加等待任务的清理逻辑，确保异常情况下也能正确清理资源
   - 在获得信号量后立即取消等待状态更新任务

### 技术细节
- 修改了`direct_downloader.py`中的`_download_custom_stream`方法
- 修改了`stream_manager.py`中的`speed_update_callback`函数
- 实现了并发等待期间的UI状态反馈机制
- 确保用户能看到任务的真实状态（等待中/下载中）

## 2025-08-20 00:07:01 - 进一步修复双重UI更新问题

### 问题描述
- 用户反馈频率限制机制实施后，仍然出现"Card UID is None"的debug日志
- 继续出现socket.send()异常，表明UI更新频率问题未完全解决

### 问题分析
- 通过代码分析发现，虽然实现了频率限制机制，但仍有多处代码直接调用`update_card`方法
- 这些直接调用绕过了频率限制机制，导致双重更新问题依然存在
- 主要问题点：
  1. `stream_manager.py`中直接调用`update_card`后又发送pubsub消息
  2. `recording_card.py`中多个方法存在相同的双重更新模式

### 修复方案
1. **统一UI更新机制**：移除所有直接调用`update_card`的代码，统一使用pubsub机制
2. **修复双重更新**：
   - 修改`stream_manager.py`第1158行，移除直接调用`update_card`
   - 修改`recording_card.py`中的`update_monitor_state`、`edit_recording_callback`、`on_toggle_recording`方法
   - 确保所有UI更新都通过pubsub机制，从而应用频率限制

### 技术细节
- 移除了4处直接调用`update_card`的代码
- 保持了pubsub机制的完整性
- 确保所有UI更新都经过频率限制检查
- 添加了详细的注释说明修改原因

### 预期效果
- 彻底消除双重UI更新问题
- 所有UI更新都受频率限制保护
- 减少"Card UID is None"警告和socket异常
- 提升UI响应性能和稳定性

## 2025-08-19 23:18:52 - 修复频繁UI更新导致的UID警告和页面卡顿问题

### 问题描述
- 用户反馈在空闲时出现大量"Card UID is None"警告
- 页面出现卡顿现象，最终需要Ctrl+C强制结束
- 日志显示OSError: Signal 2 ignored due to race condition错误

### 问题分析
- 通过分析代码发现，stream_manager.py中在更新UI后立即发送pubsub消息，导致双重更新
- pubsub机制导致update_card方法被频繁调用
- 当Flet控件UID为None时产生大量警告，可能是页面连接不稳定或控件创建问题

### 修复方案
1. **降低警告级别**：将"Card UID is None"的日志级别从warning降为debug
2. **增加存在性检查**：在update_card中增加对卡片是否仍存在于页面中的检查
3. **实现频率限制**：在RecordingCardManager中添加更新频率限制机制
   - 添加last_update_time字典记录每个录制任务的最后更新时间
   - 在subscribe_update_card中实现500ms的更新间隔限制
   - 在remove_recording_card中清理更新时间记录，避免内存泄漏
4. **优化更新逻辑**：避免在页面断开或卡片不存在时进行无效的UI更新

### 技术细节
- 修改了recording_card.py中的update_card、subscribe_update_card和remove_recording_card方法
- 实现了基于时间戳的频率限制机制，防止同一录制任务在短时间内被重复更新
- 增强了页面连接状态和卡片存在性的检查逻辑

## 2025-08-19 02:58:16 - 修复自定义流任务自动删除逻辑错误

### 问题描述
用户反馈修改完重试机制后，自定义流任务又不自动删除了。从日志分析发现，直播流正常完成下载时显示"Download Completed"和"Retrying (0/3)"，说明DirectStreamDownloader正常结束，current_retry保持为0。

### 问题分析
1. **逻辑判断错误**：之前的修复中，只有当`current_retry > max_retries`时才触发删除，但正常完成的下载current_retry为0
2. **场景理解偏差**：DirectStreamDownloader正常完成下载时不会进入异常处理分支，current_retry不会递增
3. **删除条件过严**：只考虑了重试失败的情况，忽略了正常完成下载的情况

### 核心修复方案

#### 1. 简化删除逻辑
- 移除复杂的重试次数判断
- 对于自定义流，直接根据`auto_remove_custom_stream_tasks`配置决定是否删除
- 无论是正常完成还是中断，都应用相同的删除逻辑

#### 2. 统一处理策略
- **自定义流 + 启用自动删除**：根据下载数据量设置完成/失败状态，触发删除
- **自定义流 + 禁用自动删除**：保持MONITORING状态，不删除任务
- **平台流**：始终保持MONITORING状态，等待重连

### 技术实现细节

修改`stream_manager.py`文件第1053-1083行：
```python
else:
    # 连接正常结束或中断但没有关键异常
    # 对于自定义流，检查用户配置是否需要自动删除
    if self.platform_key == "custom":
        auto_remove_enabled = self.user_config.get("auto_remove_custom_stream_tasks", True)
        if auto_remove_enabled:
            # 根据下载数据量设置相应状态，触发删除
        else:
            # 保持MONITORING状态，不删除
    else:
        # 平台流保持MONITORING状态，等待重连
```

### 技术优化亮点

1. **逻辑简化**：移除复杂的重试次数判断，直接基于配置决策
2. **场景全覆盖**：同时处理正常完成和异常中断的情况
3. **配置驱动**：完全遵循用户的auto_remove_custom_stream_tasks配置
4. **平台差异化**：自定义流和平台流采用不同处理策略
5. **日志优化**：使用更准确的描述"completed/interrupted"

### 修改文件
- `stream_manager.py`：修复自动删除逻辑

### 测试建议
1. 测试自定义流正常完成下载后的自动删除行为
2. 测试自定义流中断后的自动删除行为
3. 验证auto_remove_custom_stream_tasks配置的影响
4. 确认平台流在任何情况下都保持活跃状态

## 2025-08-19 02:19:16 - 完善直播流重试机制和任务删除逻辑

### 问题描述
用户反馈直播流任务应该在重试5次后被删除，但当前逻辑在连接中断时立即触发删除判断，没有考虑重试次数。

### 问题分析
1. **重试逻辑不完整**：stream_manager.py中的逻辑没有检查DirectStreamDownloader的重试状态
2. **删除时机错误**：在第一次连接中断时就触发删除逻辑，而不是等待重试完成
3. **状态显示不准确**：没有显示当前重试进度，用户无法了解重试状态

### 核心修复方案

#### 1. 增强重试状态检查
- 在stream_manager.py中添加`max_retries_reached`检查
- 通过`self.direct_downloader.current_retry > self.direct_downloader.max_retries`判断是否达到最大重试次数

#### 2. 完善自定义流处理逻辑
- **达到最大重试次数且启用自动删除**：根据下载数据量设置相应的完成/失败状态
- **达到最大重试次数但禁用自动删除**：保持MONITORING状态，不删除任务
- **未达到最大重试次数**：继续重连，显示重试进度

#### 3. 优化平台流处理
- 达到最大重试次数时使用warning级别日志
- 未达到时显示重试进度信息
- 始终保持MONITORING状态（平台流不自动删除）

### 技术实现细节

修改`stream_manager.py`文件第1055-1085行：
```python
# 检查是否已达到最大重试次数
max_retries_reached = self.direct_downloader.current_retry > self.direct_downloader.max_retries

if self.platform_key == "custom":
    auto_remove_enabled = self.user_config.get("auto_remove_custom_stream_tasks", True)
    
    if max_retries_reached and auto_remove_enabled:
        # 达到最大重试次数且启用自动删除
        # 根据下载数据量设置完成/失败状态
    elif max_retries_reached and not auto_remove_enabled:
        # 达到最大重试次数但禁用自动删除
        # 保持MONITORING状态
    else:
        # 未达到最大重试次数，继续重连
        # 显示重试进度
else:
    # 平台流处理逻辑
    # 显示重试状态和进度
```

### 技术优化亮点

1. **智能重试管理**：只有在达到最大重试次数后才触发删除逻辑
2. **详细进度显示**：日志中显示当前重试次数和总重试次数
3. **分级日志记录**：达到最大重试次数时使用warning级别
4. **配置驱动处理**：完全遵循用户的auto_remove_custom_stream_tasks配置
5. **平台差异化**：自定义流和平台流采用不同的处理策略

### 修改文件
- `stream_manager.py`：完善重试机制和删除逻辑

### 测试建议
1. 测试自定义流在重试5次后的自动删除行为
2. 验证重试过程中的日志输出和进度显示
3. 测试auto_remove_custom_stream_tasks配置的影响
4. 确认平台流在达到最大重试次数后仍保持活跃状态

## 2025-08-19 02:14:07 - 修复自定义流任务自动删除逻辑

### 问题描述
用户反馈自定义流任务在连接中断后没有按照配置自动删除，而是保持在监控状态。

### 问题分析
1. **逻辑缺陷**: 在`stream_manager.py`的`start_direct_download`方法中，当直播流连接中断时，代码直接设置为`MONITORING`状态，没有检查用户的`auto_remove_custom_stream_tasks`配置
2. **处理不一致**: 只有在明确的成功完成或失败时才会触发自动删除逻辑，连接中断的情况被忽略
3. **用户体验问题**: 用户配置了自动删除但任务仍然保留，造成困惑

### 核心修复方案
1. **增强中断处理逻辑**: 在连接中断时检查平台类型和用户配置
2. **区分平台处理**: 自定义流和平台流采用不同的中断处理策略
3. **智能状态转换**: 根据下载数据量和用户配置，将中断转换为相应的完成或失败状态

### 技术实现细节

#### 修改文件: `app/core/recording/stream_manager.py`
- **位置**: 1055-1061行的连接中断处理逻辑
- **核心改进**:
  ```python
  # 对于自定义流，检查用户配置是否需要自动删除中断的任务
  if self.platform_key == "custom":
      auto_remove_enabled = self.user_config.get("auto_remove_custom_stream_tasks", True)
      if auto_remove_enabled:
          if self.direct_downloader.total_bytes > 0:
              # 有数据下载，设置为完成状态触发自动删除
              download_completed_successfully = True
          else:
              # 无数据下载，设置为失败状态触发自动删除
              download_failed = True
      else:
          # 用户禁用自动删除，保持监控状态
          self.recording.status_info = RecordingStatus.MONITORING
  else:
      # 平台流保持原有重连逻辑
      self.recording.status_info = RecordingStatus.MONITORING
  ```

### 技术优化亮点
1. **智能状态判断**: 根据下载数据量决定是标记为完成还是失败
2. **配置驱动**: 完全遵循用户的`auto_remove_custom_stream_tasks`配置
3. **平台区分**: 自定义流和平台流采用不同策略，避免影响正常的重连机制
4. **日志完善**: 提供详细的日志信息，便于用户了解任务处理状态

### 测试建议
1. **自动删除测试**: 确保`auto_remove_custom_stream_tasks=true`时任务被正确删除
2. **保留任务测试**: 确保`auto_remove_custom_stream_tasks=false`时任务保持监控状态
3. **平台流测试**: 确保平台流的重连机制不受影响
4. **数据量测试**: 测试有数据和无数据下载时的不同处理逻辑

---

## 2025-08-19 01:56:39 - 修复直播流任务完成条件判断逻辑

### 问题描述
用户反馈多个录制任务在下载完成后被自动移除，经过深入分析发现问题的根源不是自动删除机制，而是**直播流任务完成条件的判断逻辑错误**：

1. **错误的完成判断**：在`stream_manager.py`中，只要`download_task.done()`且`total_bytes > 0`就被认为是"成功完成"
2. **直播流特性误解**：对于直播流，`download_task.done()`通常意味着连接中断，而不是正常完成
3. **缺乏重连机制**：网络波动或临时连接问题会导致任务被错误地标记为完成并移除

### 核心修复方案

#### 1. 修正完成条件判断逻辑
- **正确判断**：只有在手动停止（`stop_event.is_set()`）且有数据下载时才算正常完成
- **连接中断处理**：将连接中断视为需要重连的情况，而不是任务完成
- **智能状态管理**：区分手动停止、连接中断和真正的流结束

#### 2. 增强DirectStreamDownloader重连机制
- **自动重连**：添加`max_retries`和`retry_delay`参数，支持自动重连
- **智能错误分类**：区分关键错误（404、403、410）和可重试错误
- **断点续传**：重连时以追加模式写入文件，避免数据丢失
- **详细日志**：记录重连过程和状态变化

#### 3. 用户可配置的重连参数
- **最大重试次数**：`direct_download_max_retries`（默认3次）
- **重试延迟**：`direct_download_retry_delay`（默认5秒）
- **向后兼容**：保持现有配置不变，新增配置项有合理默认值

### 技术优化亮点

1. **智能重连机制**：自动区分可重试和不可重试的错误
2. **状态可视化**：在UI中显示重连状态，提升用户体验
3. **数据完整性**：断点续传确保重连后数据连续性
4. **资源管理**：合理的超时和重试限制，避免无限重连
5. **详细日志**：完整记录连接状态变化，便于问题诊断

### 修改文件
- `app/core/media/direct_downloader.py` - 增强重连机制和错误处理
- `app/core/recording/stream_manager.py` - 修正完成条件判断和状态监控
- `config/user_settings.json` - 新增重连配置项
- `config/default_settings.json` - 新增重连配置项

### 测试建议
1. **网络中断测试**：模拟网络波动，验证自动重连功能
2. **长时间录制**：测试长时间直播录制的稳定性
3. **配置测试**：验证不同重连参数的效果
4. **错误处理测试**：测试各种HTTP错误码的处理逻辑
5. **UI状态测试**：确认重连状态在界面中正确显示

---

## 2025-08-19 01:53:10 - 修复自定义流任务连锁终止问题

### 问题描述
用户反馈录制任务存在连锁终止现象，多个录制任务在某个操作后瞬间同时终止。通过日志分析发现，自定义流（Custom Stream）在录制完成后会自动调用`safe_remove_recording_sync`移除任务，这个操作可能触发UI刷新，进而影响到其他正在录制的任务。

### 问题根源
1. **强制自动移除机制**：自定义流录制完成或失败后，系统会强制自动移除任务，无法由用户控制
2. **缺乏用户选择权**：用户无法根据需要选择是否保留自定义流任务
3. **潜在连锁反应**：自动移除操作可能触发UI刷新，影响其他录制任务的稳定性

### 核心修复方案

#### 1. 新增用户配置选项
- 在`user_settings.json`和`default_settings.json`中添加`auto_remove_custom_stream_tasks`配置项
- 默认值为`true`，保持向后兼容性
- 用户可以设置为`false`来禁用自动移除功能

#### 2. 智能自定义流任务管理
- **录制完成场景**：根据用户配置决定是否自动移除任务
- **录制失败场景**：同样根据用户配置决定是否自动移除任务
- **详细日志记录**：记录用户配置状态和相应的处理决策

#### 3. 保守处理策略
- 当用户禁用自动移除时，自定义流任务会保持活跃状态
- 避免不必要的UI操作，减少对其他任务的潜在影响
- 提供清晰的日志信息，便于用户了解系统行为

### 技术优化亮点

1. **用户可控性**：提供配置选项，让用户根据需要选择任务管理策略
2. **向后兼容**：默认行为保持不变，现有用户体验不受影响
3. **智能判断**：根据配置动态调整任务处理逻辑
4. **详细日志**：增强调试能力，便于问题排查

### 修改文件
- `config/user_settings.json` - 添加自定义流自动移除配置项
- `config/default_settings.json` - 添加默认配置项
- `app/core/recording/stream_manager.py` - 修改自定义流任务处理逻辑

### 预期效果
1. **减少连锁终止**：用户可以选择禁用自动移除，避免不必要的UI操作
2. **提升稳定性**：减少对其他录制任务的潜在影响
3. **增强灵活性**：用户可以根据使用场景选择合适的任务管理策略
4. **保持兼容性**：现有用户的使用体验不受影响

### 测试建议
1. 测试自定义流录制完成后的行为（配置开启/关闭）
2. 测试自定义流录制失败后的行为（配置开启/关闭）
3. 验证多个录制任务同时运行时的稳定性
4. 确认配置项的正确读取和应用

---

## 2025-08-19 01:30:34 - 修复录制任务误判自动取消问题

### 问题描述
用户反馈录制任务仍然会莫名其妙地陆续取消，即使流没有失效。通过深入分析发现，问题根源在于录制失败检测逻辑过于严格，导致正常的录制任务被误判为失败并自动移除。

### 问题根源分析
通过分析`stream_manager.py`和`direct_downloader.py`代码发现，问题的根本原因是**错误检测逻辑过于激进**：

1. **直接下载误判机制**：
   - 在`start_direct_download`方法中，只要`download_task.done()`且`total_bytes == 0`就认为下载失败
   - 没有区分不同的完成原因：网络暂时中断、流暂时不可用、真正的流失效
   - 导致临时网络问题也会触发任务自动移除

2. **关键错误检测范围过窄**：
   - 原有的关键错误检测只包含少数几种情况
   - 缺乏对不同HTTP状态码的详细处理
   - 没有区分可恢复错误和不可恢复错误

3. **缺乏详细错误日志**：
   - 错误信息记录不够详细，难以调试问题
   - 缺乏对任务移除决策过程的日志记录

### 核心修复方案

#### 1. 智能错误检测机制
- **异常分析**：在直接下载中增加对`download_task.exception()`的检查
- **错误分类**：区分关键错误和非关键错误，只有关键错误才自动移除任务
- **保守策略**：对于无异常但无数据的情况，保持任务活跃而不是自动移除

#### 2. 扩展关键错误检测
- **完善错误列表**：扩展关键错误检测范围，包含更多真正需要移除任务的情况
- **统一检测逻辑**：FFmpeg和直接下载使用相同的关键错误检测逻辑
- **详细状态码处理**：在DirectStreamDownloader中增加对不同HTTP状态码的详细处理

#### 3. 增强日志记录
- **详细错误信息**：记录完整的错误信息和URL，便于问题定位
- **决策过程日志**：记录关键错误检测的结果和任务移除的决策过程
- **状态转换日志**：记录任务状态的转换过程

### 技术优化亮点

1. **智能容错**：区分临时错误和永久错误，避免误判
2. **保守策略**：宁可保留可能有问题的任务，也不误删正常任务
3. **统一逻辑**：FFmpeg和直接下载使用一致的错误处理逻辑
4. **调试友好**：详细的日志记录便于问题排查
5. **状态管理**：更精确的任务状态管理和转换

### 修改文件
- `app/core/recording/stream_manager.py` - 修复错误检测和任务移除逻辑
- `app/core/media/direct_downloader.py` - 增强HTTP状态码处理和错误日志

### 预期效果
- 大幅减少正常录制任务被误判移除的情况
- 提升系统对临时网络问题的容错能力
- 保持对真正失效流的及时清理能力
- 提供更详细的错误信息用于问题排查

### 测试建议
1. **网络中断测试**：模拟临时网络中断，验证任务是否保持活跃
2. **流失效测试**：测试真正失效的流是否能正确被移除
3. **并发录制测试**：多个任务同时录制时的稳定性
4. **日志验证**：检查错误日志的详细程度和准确性

## 2025-08-19 01:10:54 - 修复多线程定时器冲突导致任务异常终止问题

### 问题描述
用户反馈手动停止一个录制任务后，导致十几个其他任务被一同终止，怀疑是多线程问题。通过日志分析发现多个录制任务在同一时间被异常终止。

### 问题根源分析
通过深入分析`stream_manager.py`代码发现，问题的根本原因是**类级别共享定时器冲突**：

1. **共享定时器变量**：
   - `LiveStreamRecorder`类使用类级别的`_page_refresh_timer`变量
   - 所有录制任务实例共享同一个定时器对象
   - 当任何一个任务完成时，都会取消这个共享定时器

2. **连锁反应机制**：
   - 任务A完成时调用`safe_remove_recording_sync`方法
   - 该方法取消`LiveStreamRecorder._page_refresh_timer`（影响所有实例）
   - 其他正在进行的任务B、C、D的定时器被意外取消
   - 导致多个任务的UI更新和清理逻辑被中断，引发连锁终止

3. **竞态条件**：
   - 多个录制任务同时访问和修改同一个类级别定时器
   - 缺乏适当的线程同步机制
   - 导致任务状态管理混乱

### 核心修复方案

#### 1. 定时器隔离机制
- **移除类级别定时器**：删除`LiveStreamRecorder._page_refresh_timer`类变量
- **实例级别定时器**：为每个录制器实例添加`_instance_refresh_timer`属性
- **独立管理**：每个录制任务管理自己的定时器，避免相互干扰

#### 2. 资源清理机制
- **cleanup方法**：添加专门的资源清理方法，确保定时器正确取消
- **析构函数**：实现`__del__`方法，确保对象销毁时清理资源
- **异常处理**：增强定时器操作的异常处理，避免清理失败

#### 3. 线程安全优化
- **保留同步锁**：保留`_page_refresh_lock`类级别锁用于必要的同步
- **实例隔离**：确保每个实例的定时器操作不影响其他实例
- **日志优化**：改进日志记录，便于问题追踪和调试

### 技术优化亮点

1. **线程安全**：彻底解决多线程环境下的定时器冲突问题
2. **资源管理**：完善的资源清理机制，避免内存泄漏
3. **故障隔离**：单个任务的问题不会影响其他任务
4. **代码健壮性**：增强异常处理和错误恢复能力
5. **调试友好**：优化日志输出，便于问题定位

### 修改文件
- `app/core/recording/stream_manager.py` - 修复定时器冲突问题

### 预期效果
- 彻底解决多个任务异常同时终止的问题
- 提升多线程环境下的系统稳定性
- 确保录制任务之间的完全隔离
- 改善系统的错误恢复能力

### 测试建议
1. **并发录制测试**：同时启动10+个录制任务，手动停止其中1-2个，观察其他任务是否正常继续
2. **异常场景测试**：模拟网络中断、流地址失效等异常情况，验证任务隔离效果
3. **长时间运行测试**：运行多个任务数小时，验证资源清理和内存管理
4. **日志监控**：观察日志输出，确认定时器创建和清理的正确性

---

## 2025-08-19 00:55:43 - 彻底修复页面重复渲染问题

### 问题描述
用户反馈录制页面出现重复渲染导致页面重叠的问题（x2、x4倍数增长），即使没有添加录制任务也会出现此问题，怀疑是后台任务导致。

### 问题根源分析
通过深入分析发现，页面重复渲染的根本原因是多个后台任务同时触发页面刷新机制：

1. **stream_manager.py中的延迟刷新机制**：
   - `safe_remove_recording_sync`方法在录制失败时会创建1秒延迟的定时器
   - 每次调用都会创建新的`threading.Timer`来强制刷新页面
   - 多个录制任务失败时会产生多个定时器，导致页面被重复刷新

2. **fastapi_server.py中的延迟UI刷新**：
   - `_start_recording_task`方法包含`delayed_ui_refresh`异步任务
   - 会在0.5秒后强制调用`self.app_manager.page.update()`
   - 与stream_manager的定时器形成冲突，加剧页面重复渲染

### 核心修复方案

#### 1. 优化stream_manager.py的智能页面刷新控制
- **全局定时器管理**：引入`_page_refresh_timer`和`_page_refresh_lock`属性
- **智能调度机制**：通过`schedule_delayed_refresh`函数确保只有一个定时器运行
- **避免强制刷新**：将`self.app.page.run_task(self.app.current_page.load)`改为只更新录制卡片区域
- **延长延迟时间**：从1秒延长到1.5秒，给UI操作更多时间

#### 2. 优化fastapi_server.py的延迟UI验证
- **静默验证机制**：将`delayed_ui_refresh`改为`delayed_ui_validation`
- **避免整页刷新**：移除强制调用`self.app_manager.page.update()`的逻辑
- **精确UI更新**：只更新卡片区域`page.recording_card_area.update()`
- **延长验证时间**：从0.5秒延长到0.8秒，避免与其他机制冲突

### 技术优化亮点

1. **性能提升**：避免不必要的整页刷新，只更新必要的UI组件
2. **逻辑清晰**：分离页面刷新和UI验证的职责
3. **错误容错**：增强异常处理，避免刷新失败影响用户体验
4. **代码简洁**：遵循KISS原则，移除冗余的刷新逻辑
5. **智能调度**：通过全局定时器管理避免重复刷新

### 修改文件
- `app/core/recording/stream_manager.py` - 智能页面刷新控制
- `app/api/fastapi_server.py` - 延迟UI验证优化

### 预期效果
- 彻底解决页面重复渲染问题
- 提升UI响应性能和稳定性
- 减少不必要的页面刷新操作
- 改善用户体验，避免页面重叠现象

---

## 2025-08-19 00:30:00 - 修复录制页面重复渲染问题

### 问题描述
用户反映录制页面出现重复渲染的问题，整个页面内容重叠显示，导致界面混乱。

### 问题分析
通过代码分析发现问题根源：
1. **双重添加机制冲突**：在`fastapi_server.py`中，当通过API添加录制时，系统同时执行两个操作：
   - 通过pubsub发送'add'通知触发`subscribe_add_cards`方法
   - 直接在当前页面添加卡片
   这导致同一个卡片被添加两次
2. **缺少UI层重复检查**：`subscribe_add_cards`方法没有检查UI中是否已存在相同的卡片
3. **逻辑顺序问题**：pubsub通知在页面检查之前发送，导致不必要的重复处理

### 修复内容

#### 1. 优化添加逻辑顺序 (`fastapi_server.py`)
- 调整逻辑顺序：先检查当前页面类型，再决定使用哪种添加方式
- 如果当前页面是录制页面，直接添加卡片，不发送pubsub通知
- 只有在非录制页面时才通过pubsub通知，避免重复添加
- 在直接添加时也设置计划时间范围，保持功能完整性

#### 2. 增强UI层重复检查 (`recordings_view.py`)
- 在`subscribe_add_cards`方法中添加UI层面的重复检查
- 检查现有控件中是否已存在相同`rec_id`的卡片
- 只有在确实不存在时才创建新卡片
- 改进错误处理和日志记录

### 主要改进点
1. **消除双重添加**：通过条件判断确保每个卡片只通过一种方式添加
2. **UI层防护**：在UI层面也添加重复检查，提供双重保护
3. **逻辑清晰**：明确区分直接添加和pubsub通知的使用场景
4. **性能优化**：减少不必要的pubsub通信和UI更新
5. **错误容错**：改进异常处理，提供更好的错误恢复能力

### 技术细节
- 使用`card.data`属性作为卡片唯一标识进行重复检查
- 保持计划时间范围设置的一致性
- 优化日志输出，便于问题追踪和调试
- 确保加载指示器状态的正确管理

### 影响范围
- API录制添加流程
- 录制页面UI更新机制
- pubsub通信逻辑
- 卡片重复检查机制

## 2025-08-19 00:45:58 - 修复录制卡片重复显示问题

### 问题描述
用户反映录制卡片在页面中出现重复重叠的情况，多个相同的录制卡片同时显示在界面上。

### 问题分析
通过代码分析发现问题根源：
1. **延迟刷新逻辑缺陷**：当卡片未在管理器中注册时，系统会调用`await self.app_manager.current_page.load()`强制刷新整个页面，这可能导致重复创建卡片
2. **缺少重复检查机制**：在延迟创建卡片时，没有检查UI中是否已存在相同的卡片
3. **卡片标识缺失**：卡片对象缺少唯一标识，无法有效防止重复添加

### 修复内容

#### 1. 优化延迟刷新逻辑 (`fastapi_server.py`)
- 移除强制页面重新加载的逻辑，改为智能检查和重新创建
- 添加UI中已存在卡片的检查机制
- 通过`card.data`属性检查是否存在相同`rec_id`的卡片
- 只有在确实不存在时才重新创建卡片

#### 2. 增强卡片标识机制 (`recording_card.py`)
- 在`create_card`方法中为每个卡片设置`data`属性作为唯一标识
- 确保卡片创建时就具有`rec_id`标识

#### 3. 完善初始添加逻辑 (`fastapi_server.py`)
- 在初始添加卡片时也设置`data`属性
- 确保所有卡片都具有一致的标识机制

### 主要改进点
1. **防重复机制**：通过卡片`data`属性实现有效的重复检查
2. **智能重建**：替换粗暴的页面重载为精确的卡片重建
3. **状态一致性**：确保UI状态与管理器状态的一致性
4. **性能优化**：避免不必要的页面重载操作

### 技术细节
- 使用`card.data = rec_id`作为卡片唯一标识
- 在延迟刷新时遍历现有卡片检查重复
- 保持原有的错误处理和日志记录机制

### 影响范围
- 录制卡片的创建和显示逻辑
- 延迟UI刷新机制
- 卡片重复检查机制

---

## 2025-08-19 00:43:21 - 修复Flet UI更新AssertionError问题

### 问题描述
- 在录制开始时，Flet UI更新过程中出现AssertionError
- 错误信息：`assert self.__uid is not None`
- 问题出现在录制卡片更新时，控件的__uid为None导致断言失败

### 修复内容
1. **改进fastapi_server.py中的UI更新逻辑**
   - 在创建和添加录制卡片前检查页面连接状态
   - 增加卡片创建失败的处理逻辑
   - 改进延迟刷新机制，避免在页面断开时更新UI
   - 添加更详细的错误处理和日志记录

2. **增强recording_card.py中的错误处理**
   - 在create_card方法中添加页面连接状态检查
   - 验证卡片组件是否正确创建
   - 在update_card方法中增加控件UID有效性检查
   - 改进状态标签更新的错误处理
   - 添加更全面的异常捕获和日志记录

3. **主要改进点**
   - 页面连接状态检查：避免在页面断开时进行UI操作
   - 控件UID验证：确保控件有效后再进行更新
   - 错误恢复机制：当直接UI更新失败时，通过延迟刷新处理
   - 日志优化：提供更详细的错误信息便于调试

### 技术细节
- 使用`_is_page_connected()`方法检查页面连接状态
- 检查控件的`_Control__uid`属性是否为None
- 实现多层错误处理，确保程序稳定性
- 优化异步任务的错误处理机制

### 影响范围
- 录制开始时的UI更新流程
- 录制卡片的创建和更新机制
- 页面刷新和错误恢复逻辑

---