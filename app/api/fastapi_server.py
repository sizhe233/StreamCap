"""
FastAPI服务器，提供录制控制API接口
"""
import asyncio
import threading
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from ..utils.logger import logger
from ..core.platforms.platform_handlers import CustomHandler


class RecordRequest(BaseModel):
    """
    录制请求模型
    
    用于开始录制直播的请求参数
    """
    anchor_name: str = Field(
        ..., 
        description="主播名称",
        example="测试主播001",
        min_length=1,
        max_length=100
    )
    stream_url: str = Field(
        ..., 
        description="FLV或HLS流地址，必须包含.flv或.m3u8",
        example="https://example.com/live/stream.flv"
    )
    record_quality: str = Field(
        default="OD", 
        description="录制质量：OD(原画)、UHD(4K)、HD(1080p)、SD(720p)、LD(480p)",
        example="OD"
    )
    output_dir: Optional[str] = Field(
        default=None, 
        description="输出目录路径，为空时使用系统默认设置",
        example="D:/录制文件/主播001"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "anchor_name": "测试主播001",
                "stream_url": "https://example.com/live/stream.flv",
                "record_quality": "OD",
                "output_dir": "D:/录制文件/主播001"
            }
        }


class RecordResponse(BaseModel):
    """
    录制响应模型
    
    录制操作的返回结果
    """
    success: bool = Field(
        ..., 
        description="操作是否成功"
    )
    message: str = Field(
        ..., 
        description="操作结果消息"
    )
    record_id: Optional[str] = Field(
        default=None, 
        description="录制任务ID，成功时返回"
    )

    class Config:
        schema_extra = {
            "example": {
                "success": True,
                "message": "成功开始录制 测试主播001",
                "record_id": "abc123def456"
            }
        }


class StopRecordRequest(BaseModel):
    """
    停止录制请求模型
    
    用于停止录制的请求参数，record_id 和 anchor_name 二选一
    """
    record_id: Optional[str] = Field(
        default=None, 
        description="录制任务ID（通过开始录制接口获得）",
        example="abc123def456"
    )
    anchor_name: Optional[str] = Field(
        default=None, 
        description="主播名称（精确匹配）",
        example="测试主播001"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "record_id": "abc123def456"
            }
        }


class FastAPIServer:
    """FastAPI服务器类"""
    
    def __init__(self, app_manager=None, host: str = "127.0.0.1", port: int = 8000):
        self.app_manager = app_manager
        self.host = host
        self.port = port
        self.server = None
        self.server_thread = None
        self.is_running = False
        
        # 创建FastAPI应用
        self.fastapi_app = FastAPI(
            title="StreamCap 直播录制 API",
            description="""
## StreamCap 直播录制控制 API

这是一个用于控制直播录制的 RESTful API 服务。

### 主要功能
- 🎥 **开始录制**: 通过提供主播名称和流地址开始录制
- ⏹️ **停止录制**: 根据录制ID或主播名称停止录制
- 📊 **状态查询**: 查看所有录制任务或单个主播的录制状态
- 🔍 **模糊搜索**: 支持使用通配符(%)进行主播名称模糊匹配

### 支持的流格式
- FLV 格式 (.flv)
- HLS 格式 (.m3u8)

### 录制质量选项
- **OD**: 原画质量
- **UHD**: 超高清 (4K)
- **HD**: 高清 (1080p)
- **SD**: 标清 (720p)
- **LD**: 流畅 (480p)

### 使用说明
1. 首先调用 `/record/start` 开始录制
2. 使用 `/record/status` 查看录制状态
3. 需要时调用 `/record/stop` 停止录制
            """,
            version="1.0.0",
            contact={
                "name": "StreamCap 开发团队",
                "url": "https://github.com/your-repo/streamcap",
            },
            license_info={
                "name": "MIT License",
                "url": "https://opensource.org/licenses/MIT",
            },
        )
        
        # 添加CORS中间件
        self.fastapi_app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # 允许所有来源，生产环境建议指定具体域名
            allow_credentials=True,
            allow_methods=["*"],  # 允许所有HTTP方法
            allow_headers=["*"],  # 允许所有请求头
        )
        
        # 注册路由
        self._setup_routes()
    
    def _setup_routes(self):
        """设置API路由"""
        
        @self.fastapi_app.get(
            "/",
            summary="API 根路径",
            description="返回 API 服务器的基本信息和运行状态",
            tags=["系统信息"]
        )
        async def root():
            """
            ## API 根路径
            
            返回 StreamCap API 服务器的基本信息。
            
            **返回信息:**
            - 服务器名称
            - 运行状态
            """
            return {"message": "StreamCap API Server", "status": "running"}
        
        @self.fastapi_app.get(
            "/health",
            summary="健康检查",
            description="检查 API 服务器的健康状态",
            tags=["系统信息"]
        )
        async def health_check():
            """
            ## 健康检查端点
            
            用于监控和检查 API 服务器是否正常运行。
            
            **返回信息:**
            - 服务器健康状态
            - 服务器运行状态
            """
            return {"status": "healthy", "server_running": self.is_running}
        
        @self.fastapi_app.post(
            "/record/start", 
            response_model=RecordResponse,
            summary="开始录制直播",
            description="根据提供的主播名称和流地址开始录制直播",
            tags=["录制控制"]
        )
        async def start_record(request: RecordRequest, background_tasks: BackgroundTasks):
            """
            ## 开始录制直播
            
            根据提供的主播名称和流地址开始录制直播。
            
            **请求参数:**
            - `anchor_name`: 主播名称（必填）
            - `stream_url`: FLV 或 HLS 流地址（必填）
            - `record_quality`: 录制质量，可选值：OD（原画）、UHD（4K）、HD（1080p）、SD（720p）、LD（480p）
            - `output_dir`: 输出目录（可选，默认使用系统设置）
            
            **支持的流格式:**
            - FLV 格式：包含 .flv 的 URL
            - HLS 格式：包含 .m3u8 的 URL
            
            **返回结果:**
            - `success`: 是否成功
            - `message`: 操作结果消息
            - `record_id`: 录制任务ID（成功时返回）
            
            **注意事项:**
            - 同一主播名称只能有一个录制任务
            - 流地址必须是有效的 FLV 或 M3U8 格式
            """
            try:
                if not self.app_manager:
                    raise HTTPException(status_code=500, detail="应用管理器未初始化")
                
                # 验证流地址格式 - 支持带查询参数的FLV和M3U8地址
                url_lower = request.stream_url.lower()
                if not ('.flv' in url_lower or '.m3u8' in url_lower):
                    raise HTTPException(status_code=400, detail="不支持的流地址格式，仅支持FLV和HLS(m3u8)格式")
                
                # 检查主播名称是否已存在
                record_manager = self.app_manager.record_manager
                if not record_manager:
                    raise HTTPException(status_code=500, detail="录制管理器未初始化")
                
                # 检查是否有同名主播的录制任务
                existing_recordings = record_manager.recordings
                for recording in existing_recordings:
                    if recording.streamer_name.lower() == request.anchor_name.lower():
                        return RecordResponse(
                            success=False,
                            message=f"已存在同名主播的录制任务: {request.anchor_name}",
                            record_id=None
                        )
                
                # 创建自定义处理器
                custom_handler = CustomHandler(
                    record_quality=request.record_quality or "OD"
                )
                
                # 获取流信息
                stream_data = await custom_handler.get_stream_info(request.stream_url)
                stream_data.anchor_name = request.anchor_name
                
                # 添加录制任务
                record_id = await self._start_recording_task(
                    record_manager, 
                    stream_data, 
                    request
                )
                
                logger.info(f"通过API开始录制: {request.anchor_name} - {request.stream_url}")
                
                return RecordResponse(
                    success=True,
                    message=f"成功开始录制 {request.anchor_name}",
                    record_id=record_id
                )
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"API录制启动失败: {str(e)}")
                raise HTTPException(status_code=500, detail=f"录制启动失败: {str(e)}")
        
        @self.fastapi_app.post(
            "/record/stop", 
            response_model=RecordResponse,
            summary="停止录制",
            description="根据录制ID或主播名称停止正在进行的录制任务",
            tags=["录制控制"]
        )
        async def stop_record(request: StopRecordRequest):
            """
            ## 停止录制
            
            根据录制ID或主播名称停止正在进行的录制任务。
            
            **请求参数（二选一）:**
            - `record_id`: 录制任务ID（通过开始录制接口获得）
            - `anchor_name`: 主播名称（精确匹配）
            
            **返回结果:**
            - `success`: 是否成功停止
            - `message`: 操作结果消息
            
            **使用示例:**
            ```json
            // 通过录制ID停止
            {
                "record_id": "abc123def456"
            }
            
            // 通过主播名称停止
            {
                "anchor_name": "主播名称"
            }
            ```
            
            **注意事项:**
            - 必须提供 record_id 或 anchor_name 其中之一
            - 如果录制任务不存在，将返回失败信息
            """
            try:
                if not self.app_manager:
                    raise HTTPException(status_code=500, detail="应用管理器未初始化")
                
                record_manager = self.app_manager.record_manager
                if not record_manager:
                    raise HTTPException(status_code=500, detail="录制管理器未初始化")
                
                # 根据record_id或anchor_name停止录制
                stopped = False
                if request.record_id:
                    stopped = await self._stop_recording_by_id(record_manager, request.record_id)
                elif request.anchor_name:
                    stopped = await self._stop_recording_by_name(record_manager, request.anchor_name)
                else:
                    raise HTTPException(status_code=400, detail="必须提供record_id或anchor_name")
                
                if stopped:
                    logger.info(f"通过API停止录制: {request.record_id or request.anchor_name}")
                    return RecordResponse(
                        success=True,
                        message="录制已停止"
                    )
                else:
                    return RecordResponse(
                        success=False,
                        message="未找到对应的录制任务"
                    )
                    
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"API录制停止失败: {str(e)}")
                raise HTTPException(status_code=500, detail=f"录制停止失败: {str(e)}")
        
        @self.fastapi_app.get(
            "/record/status",
            summary="获取所有录制状态",
            description="获取当前所有活跃录制任务的状态信息",
            tags=["状态查询"]
        )
        async def get_record_status():
            """
            ## 获取所有录制状态
            
            获取当前所有活跃录制任务的状态信息。
            
            **返回结果:**
            - `active_records`: 活跃录制任务列表
            - `total_count`: 活跃录制任务总数
            
            **录制任务信息包含:**
            - `record_id`: 录制任务ID
            - `anchor_name`: 主播名称
            - `stream_url`: 流地址
            - `is_monitoring`: 是否正在监控
            - `is_recording`: 是否正在录制
            - `status`: 当前状态描述
            - `start_time`: 开始时间（如果已开始）
            
            **状态说明:**
            - `监控中`: 正在监控直播状态，等待开播
            - `录制中`: 正在录制直播内容
            - `已停止监控`: 监控已停止
            - `录制错误`: 录制过程中出现错误
            """
            try:
                if not self.app_manager or not self.app_manager.record_manager:
                    return {"active_records": [], "total_count": 0}
                
                # 获取活跃录制列表
                active_records = await self._get_active_records()
                
                return {
                    "active_records": active_records,
                    "total_count": len(active_records)
                }
                
            except Exception as e:
                logger.error(f"获取录制状态失败: {str(e)}")
                raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")
        
        @self.fastapi_app.get(
            "/record/status/{anchor_name}",
            summary="获取单个主播录制状态",
            description="获取指定主播的录制状态，支持模糊查询和通配符匹配",
            tags=["状态查询"]
        )
        async def get_single_record_status(anchor_name: str):
            """
            ## 获取单个主播录制状态
            
            获取指定主播的录制状态信息，支持模糊查询和通配符匹配。
            
            **路径参数:**
            - `anchor_name`: 主播名称（支持模糊匹配）
            
            **模糊查询支持:**
            - 精确匹配：`主播名称`
            - 前缀匹配：`主播%`（查找以"主播"开头的）
            - 后缀匹配：`%名称`（查找以"名称"结尾的）
            - 包含匹配：`%主播%`（查找包含"主播"的）
            
            **返回结果（单个匹配）:**
            - `record_id`: 录制任务ID
            - `anchor_name`: 主播名称
            - `stream_url`: 流地址
            - `is_monitoring`: 是否正在监控
            - `is_recording`: 是否正在录制
            - `status`: 当前状态描述
            - `quality`: 录制质量
            - `record_format`: 录制格式
            - `platform`: 平台信息
            - `is_live`: 是否正在直播
            - `live_title`: 直播标题（如果正在直播）
            - `start_time`: 开始时间（如果已开始）
            - `last_check_time`: 最后检查时间
            - `duration`: 录制时长
            
            **返回结果（多个匹配）:**
            - `matched_records`: 匹配的录制任务列表
            - `total_count`: 匹配数量
            - `message`: 匹配结果说明
            
            **使用示例:**
            - `/record/status/主播001` - 精确查找
            - `/record/status/主播%` - 查找所有以"主播"开头的
            - `/record/status/%测试%` - 查找所有包含"测试"的
            
            **错误情况:**
            - 404: 未找到匹配的录制任务
            - 500: 服务器内部错误
            """
            try:
                if not self.app_manager or not self.app_manager.record_manager:
                    raise HTTPException(status_code=404, detail="未找到指定主播的录制任务")
                
                # 查找指定主播的录制任务（支持模糊匹配）
                record_manager = self.app_manager.record_manager
                matched_recordings = []
                
                # 处理查询参数，支持%通配符
                search_pattern = anchor_name.lower()
                
                for recording in record_manager.recordings:
                    streamer_name_lower = recording.streamer_name.lower()
                    
                    # 支持模糊匹配
                    is_match = False
                    if '%' in search_pattern:
                        # 处理%通配符
                        pattern_parts = search_pattern.split('%')
                        if len(pattern_parts) == 2:
                            prefix, suffix = pattern_parts
                            if prefix and suffix:
                                # %在中间，如：test%user
                                is_match = streamer_name_lower.startswith(prefix) and streamer_name_lower.endswith(suffix)
                            elif prefix:
                                # %在末尾，如：test%
                                is_match = streamer_name_lower.startswith(prefix)
                            elif suffix:
                                # %在开头，如：%user
                                is_match = streamer_name_lower.endswith(suffix)
                        elif len(pattern_parts) == 3 and pattern_parts[0] == '' and pattern_parts[2] == '':
                            # 两边都有%，如：%test%
                            middle_part = pattern_parts[1]
                            is_match = middle_part in streamer_name_lower
                        else:
                            # 多个%的复杂情况，简化处理
                            pattern_without_percent = search_pattern.replace('%', '')
                            is_match = pattern_without_percent in streamer_name_lower
                    else:
                        # 精确匹配
                        is_match = streamer_name_lower == search_pattern
                    
                    if is_match:
                        record_info = {
                            "record_id": recording.rec_id,
                            "anchor_name": recording.streamer_name,
                            "stream_url": recording.url,
                            "is_monitoring": recording.monitor_status,
                            "is_recording": recording.is_recording,
                            "status": recording.status_info,
                            "quality": recording.quality,
                            "record_format": recording.record_format,
                            "platform": recording.platform,
                            "is_live": getattr(recording, 'is_live', False),
                            "live_title": getattr(recording, 'live_title', None),
                            "speed": getattr(recording, 'speed', '0 KB/s')
                        }
                        
                        # 添加时间信息
                        if recording.start_time:
                            record_info["start_time"] = recording.start_time.isoformat()
                        if hasattr(recording, 'detection_time') and recording.detection_time:
                            record_info["last_check_time"] = recording.detection_time.isoformat()
                        
                        # 添加录制时长信息
                        if hasattr(self.app_manager, 'record_manager'):
                            duration = self.app_manager.record_manager.get_duration(recording)
                            record_info["duration"] = duration
                        
                        matched_recordings.append(record_info)
                
                # 返回匹配结果
                if len(matched_recordings) == 1:
                    # 只有一个匹配结果，直接返回
                    return matched_recordings[0]
                elif len(matched_recordings) > 1:
                    # 多个匹配结果，返回列表
                    return {
                        "matched_records": matched_recordings,
                        "total_count": len(matched_recordings),
                        "message": f"找到 {len(matched_recordings)} 个匹配的主播"
                    }
                else:
                    # 没有找到匹配的录制任务
                    raise HTTPException(status_code=404, detail=f"未找到匹配 '{anchor_name}' 的录制任务")
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"获取单个主播录制状态失败: {str(e)}")
                raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")
    
    async def _start_recording_task(self, record_manager, stream_data, request):
        """启动录制任务"""
        try:
            from ..models.recording.recording_model import Recording
            import uuid
            from datetime import datetime
            
            # 创建Recording对象
            recording_data = {
                "rec_id": str(uuid.uuid4())[:8],
                "url": stream_data.record_url,
                "streamer_name": stream_data.anchor_name,
                "quality": request.record_quality or "OD",
                "record_format": "flv",  # 使用FLV格式，更安全，异常停止不会损坏文件
                "segment_record": False,
                "segment_time": 30,
                "monitor_status": False,
                "only_notify_no_record": False,
                "scheduled_recording": False,
                "scheduled_start_time": None,
                "monitor_hours": None,
                "recording_dir": request.output_dir,
                "enabled_message_push": False,
                "platform": "custom",
                "platform_key": "custom",
                "flv_use_direct_download": True
            }
            
            # 创建Recording实例
            recording = Recording.from_dict(recording_data)
            
            # 添加到录制管理器
            await record_manager.add_recording(recording)
            
            # 开始监控录制
            await record_manager.start_monitor_recording(recording)
            
            # 更新UI - 创建录制卡片并通过pubsub通知UI更新
            if hasattr(self.app_manager, 'page') and hasattr(self.app_manager.page, 'pubsub'):
                # 创建录制卡片
                if hasattr(self.app_manager, 'record_card_manager'):
                    try:
                        # 创建卡片
                        card = await self.app_manager.record_card_manager.create_card(recording)
                        
                        # 设置计划时间范围
                        recording.scheduled_time_range = await self.app_manager.record_manager.get_scheduled_time_range(
                            recording.scheduled_start_time, recording.monitor_hours
                        )
                        
                        # 通过pubsub通知UI更新，这会触发subscribe_add_cards方法
                        self.app_manager.page.pubsub.send_others_on_topic("add", recording)
                        logger.info(f"已创建录制卡片并通过pubsub通知UI更新: {recording.streamer_name}")
                    except Exception as e:
                        logger.error(f"创建录制卡片失败: {str(e)}")
                        # 即使卡片创建失败，也要发送pubsub消息
                        self.app_manager.page.pubsub.send_others_on_topic("add", recording)
                else:
                    # 如果没有record_card_manager，只发送pubsub消息
                    self.app_manager.page.pubsub.send_others_on_topic("add", recording)
                    logger.info(f"已通过pubsub通知UI更新录制任务: {recording.streamer_name}")
            
            logger.info(f"成功创建并启动录制任务: {recording.rec_id}")
            return recording.rec_id
            
        except Exception as e:
            logger.error(f"启动录制任务失败: {str(e)}")
            raise
    
    async def _stop_recording_by_id(self, record_manager, record_id):
        """根据ID停止录制"""
        try:
            # 根据record_id查找录制任务
            recording = record_manager.find_recording_by_id(record_id)
            if recording:
                await record_manager.stop_monitor_recording(recording)
                return True
            return False
        except Exception as e:
            logger.error(f"停止录制失败: {str(e)}")
            return False
    
    async def _stop_recording_by_name(self, record_manager, anchor_name):
        """根据主播名称停止录制"""
        try:
            # 根据主播名称查找录制任务
            for recording in record_manager.recordings:
                if recording.streamer_name.lower() == anchor_name.lower():
                    await record_manager.stop_monitor_recording(recording)
                    return True
            return False
        except Exception as e:
            logger.error(f"停止录制失败: {str(e)}")
            return False
    
    async def _get_active_records(self):
        """获取活跃录制列表"""
        try:
            active_records = []
            for recording in self.app_manager.record_manager.recordings:
                if recording.monitor_status or recording.is_recording:
                    record_info = {
                        "record_id": recording.rec_id,
                        "anchor_name": recording.streamer_name,
                        "stream_url": recording.url,
                        "is_monitoring": recording.monitor_status,
                        "is_recording": recording.is_recording,
                        "status": recording.status_info,
                        "speed": getattr(recording, 'speed', '0 KB/s')
                    }
                    if recording.start_time:
                        record_info["start_time"] = recording.start_time.isoformat()
                    active_records.append(record_info)
            return active_records
        except Exception as e:
            logger.error(f"获取活跃录制列表失败: {str(e)}")
            return []
    
    def start_server(self):
        """启动FastAPI服务器"""
        if self.is_running:
            logger.warning("FastAPI服务器已在运行")
            return
        
        def run_server():
            try:
                config = uvicorn.Config(
                    self.fastapi_app,
                    host=self.host,
                    port=self.port,
                    log_level="info"
                )
                self.server = uvicorn.Server(config)
                self.is_running = True
                logger.info(f"FastAPI服务器启动在 http://{self.host}:{self.port}")
                
                # 运行服务器
                asyncio.run(self.server.serve())
                
            except Exception as e:
                logger.error(f"FastAPI服务器启动失败: {str(e)}")
                self.is_running = False
        
        # 在单独线程中运行服务器
        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()
        
        logger.info("FastAPI服务器线程已启动")
    
    def stop_server(self):
        """停止FastAPI服务器"""
        if not self.is_running:
            return
        
        try:
            if self.server:
                self.server.should_exit = True
            self.is_running = False
            logger.info("FastAPI服务器已停止")
        except Exception as e:
            logger.error(f"停止FastAPI服务器失败: {str(e)}")