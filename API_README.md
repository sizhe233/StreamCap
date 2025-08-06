# StreamCap API 使用说明

StreamCap现在支持通过FastAPI接口来控制直播录制功能。您可以通过API接口直接启动和停止录制，无需通过GUI界面操作。

**注意**：API创建的录制任务默认使用FLV格式，这是一种流式格式，即使录制过程中异常停止，已录制的部分也不会丢失，比MP4格式更安全可靠。

## 服务端口说明

StreamCap运行两个服务：

1. **Web服务**：Flet应用的Web界面，默认端口为 **6006**
   - 可通过 `--port` 参数修改
   - 访问地址：`http://127.0.0.1:6006`

2. **API服务**：FastAPI接口服务，默认端口为 **8000**
   - 可通过 `--api-port` 参数修改
   - 访问地址：`http://127.0.0.1:8000`

## 可用接口

### 1. 健康检查

```
GET /health
```

返回API服务器的健康状态。

### 2. 开始录制

```
POST /record/start
```

请求体:
```json
{
  "anchor_name": "主播名称",
  "stream_url": "直播流地址",
  "record_quality": "OD",
  "output_dir": "可选的输出目录"
}
```

参数说明:
- `anchor_name`: 主播名称，用于标识录制任务（必填）
- `stream_url`: FLV或HLS直播流地址，支持包含.flv或.m3u8的URL（包括带查询参数的地址）（必填）
- `record_quality`: 录制质量，默认为"OD"（原画），可选值：OD（原画）、UHD（超高清）、HD（高清）、SD（标清）、LD（流畅）（可选）
- `output_dir`: 输出目录，不提供则使用默认设置的保存路径（可选）

最简请求体（只传必填参数）:
```json
{
  "anchor_name": "主播名称",
  "stream_url": "直播流地址"
}
```

返回示例:
```json
{
  "success": true,
  "message": "成功开始录制 主播名称",
  "record_id": "记录ID"
}
```

如果主播名称已存在，将返回错误:
```json
{
  "success": false,
  "message": "已存在同名主播的录制任务: 主播名称",
  "record_id": null
}
```

### 3. 停止录制

```
POST /record/stop
```

请求体:
```json
{
  "record_id": "记录ID",
  "anchor_name": "主播名称"
}
```

参数说明:
- `record_id`: 开始录制时返回的记录ID
- `anchor_name`: 主播名称

注意: 必须提供`record_id`或`anchor_name`中的一个

返回示例:
```json
{
  "success": true,
  "message": "录制已停止"
}
```

### 4. 获取所有录制状态

```
GET /record/status
```

返回示例:
```json
{
  "active_records": [
    {
      "record_id": "记录ID",
      "anchor_name": "主播名称", 
      "stream_url": "直播流地址",
      "is_monitoring": true,
      "is_recording": false,
      "status": "监控中",
      "start_time": "2025-08-07T02:49:34.123456"
    }
  ],
  "total_count": 1
}
```

### 5. 获取单个主播状态（支持模糊查询）

```
GET /record/status/{anchor_name}
```

参数说明:
- `anchor_name`: 主播名称（URL路径参数），支持模糊查询
  - 精确匹配：`主播名称`
  - 前缀匹配：`主播%`
  - 后缀匹配：`%名称`
  - 包含匹配：`%播名%`

**单个匹配结果**返回示例:
```json
{
  "record_id": "记录ID",
  "anchor_name": "主播名称",
  "stream_url": "直播流地址",
  "is_monitoring": true,
  "is_recording": false,
  "status": "监控中",
  "quality": "OD",
  "record_format": "flv",
  "platform": "custom",
  "is_live": true,
  "live_title": "直播标题",
  "start_time": "2025-08-07T02:49:34.123456",
  "last_check_time": "2025-08-07T02:50:00.123456",
  "duration": "00:05:30"
}
```

**多个匹配结果**返回示例:
```json
{
  "matched_records": [
    {
      "record_id": "记录ID1",
      "anchor_name": "主播名称1",
      "stream_url": "直播流地址1",
      "is_monitoring": true,
      "is_recording": false,
      "status": "监控中"
    },
    {
      "record_id": "记录ID2", 
      "anchor_name": "主播名称2",
      "stream_url": "直播流地址2",
      "is_monitoring": false,
      "is_recording": true,
      "status": "录制中"
    }
  ],
  "total_count": 2,
  "message": "找到 2 个匹配的主播"
}
```

如果没有匹配的主播，将返回404错误:
```json
{
  "detail": "未找到匹配 '查询条件' 的录制任务"
}
```

### 使用curl查询录制状态

查询所有录制状态：
```bash
curl -X GET "http://127.0.0.1:8000/record/status"
```

查询单个主播状态（精确匹配）：
```bash
curl -X GET "http://127.0.0.1:8000/record/status/主播名称"
```

查询单个主播状态（模糊匹配）：
```bash
# 前缀匹配
curl -X GET "http://127.0.0.1:8000/record/status/主播%"

# 后缀匹配  
curl -X GET "http://127.0.0.1:8000/record/status/%名称"

# 包含匹配
curl -X GET "http://127.0.0.1:8000/record/status/%播名%"
```

### 使用PowerShell查询录制状态

查询所有录制状态：
```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000/record/status" -Method GET
```

查询单个主播状态（精确匹配）：
```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000/record/status/主播名称" -Method GET
```

查询单个主播状态（模糊匹配）：
```powershell
# 前缀匹配
Invoke-WebRequest -Uri "http://127.0.0.1:8000/record/status/主播%" -Method GET

# 包含匹配
Invoke-WebRequest -Uri "http://127.0.0.1:8000/record/status/%播名%" -Method GET
```

## 使用示例

### 使用curl开始录制

完整参数示例：
```bash
curl -X POST "http://127.0.0.1:8000/record/start" \
  -H "Content-Type: application/json" \
  -d '{
    "anchor_name": "测试主播",
    "stream_url": "http://example.com/live/stream.flv",
    "record_quality": "best"
  }'
```

最简参数示例（只传必填参数）：
```bash
curl -X POST "http://127.0.0.1:8000/record/start" \
  -H "Content-Type: application/json" \
  -d '{
    "anchor_name": "测试主播",
    "stream_url": "http://example.com/live/stream.flv"
  }'
```

### 使用curl停止录制

```bash
curl -X POST "http://127.0.0.1:8000/record/stop" \
  -H "Content-Type: application/json" \
  -d '{
    "anchor_name": "测试主播"
  }'
```

### 使用Python请求

```python
import requests

# 开始录制
response = requests.post(
    "http://127.0.0.1:8000/record/start",
    json={
        "anchor_name": "测试主播",
        "stream_url": "http://example.com/live/stream.flv",
        "record_quality": "OD"
    }
)
print(response.json())

# 查询所有录制状态
response = requests.get("http://127.0.0.1:8000/record/status")
print(response.json())

# 查询单个主播状态（精确匹配）
response = requests.get("http://127.0.0.1:8000/record/status/测试主播")
print(response.json())

# 查询单个主播状态（模糊匹配）
# 前缀匹配
response = requests.get("http://127.0.0.1:8000/record/status/测试%")
print(response.json())

# 包含匹配
response = requests.get("http://127.0.0.1:8000/record/status/%主播%")
print(response.json())

# 停止录制
response = requests.post(
    "http://127.0.0.1:8000/record/stop",
    json={
        "anchor_name": "测试主播"
    }
)
print(response.json())
```

## 自定义API端口

启动StreamCap时可以通过`--api-port`参数指定API服务器的端口：

```bash
python main.py --api-port 9000
```

这将使API服务器运行在 `http://127.0.0.1:9000`。