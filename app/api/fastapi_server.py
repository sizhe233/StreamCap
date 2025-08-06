"""
FastAPI服务器，提供录制控制API接口
"""
import asyncio
import threading
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import uvicorn

from ..utils.logger import logger
from ..core.platforms.platform_handlers import CustomHandler


class RecordRequest(BaseModel):
    """录制请求模型"""
    anchor_name: str  # 主播名称
    stream_url: str   # FLV/HLS流地址
    record_quality: str = "OD"  # 录制质量，默认为OD（原画）
    output_dir: Optional[str] = None  # 输出目录，默认为None使用系统设置


class RecordResponse(BaseModel):
    """录制响应模型"""
    success: bool
    message: str
    record_id: Optional[str] = None


class StopRecordRequest(BaseModel):
    """停止录制请求模型"""
    record_id: Optional[str] = None
    anchor_name: Optional[str] = None


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
            title="StreamCap API",
            description="直播录制控制API",
            version="1.0.0"
        )
        
        # 注册路由
        self._setup_routes()
    
    def _setup_routes(self):
        """设置API路由"""
        
        @self.fastapi_app.get("/")
        async def root():
            return {"message": "StreamCap API Server", "status": "running"}
        
        @self.fastapi_app.get("/health")
        async def health_check():
            return {"status": "healthy", "server_running": self.is_running}
        
        @self.fastapi_app.post("/record/start", response_model=RecordResponse)
        async def start_record(request: RecordRequest, background_tasks: BackgroundTasks):
            """开始录制直播"""
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
                    request.output_dir
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
        
        @self.fastapi_app.post("/record/stop", response_model=RecordResponse)
        async def stop_record(request: StopRecordRequest):
            """停止录制"""
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
        
        @self.fastapi_app.get("/record/status")
        async def get_record_status():
            """获取录制状态"""
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
        
        @self.fastapi_app.get("/record/status/{anchor_name}")
        async def get_single_record_status(anchor_name: str):
            """获取单个主播的录制状态（支持模糊查询）"""
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
                            "live_title": getattr(recording, 'live_title', None)
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
    
    async def _start_recording_task(self, record_manager, stream_data, output_dir=None):
        """启动录制任务"""
        try:
            from ..models.recording.recording_model import Recording
            import uuid
            from datetime import datetime
            
            # 创建Recording对象
            recording_data = {
                "url": stream_data.record_url,
                "streamer_name": stream_data.anchor_name,
                "quality": request.record_quality or "OD",
                "record_format": "flv",  # 使用FLV格式，更安全，异常停止不会损坏文件
                "segment_record": False,
                "segment_time": 30,
                "only_notify_no_record": False,
                "scheduled_recording": False,
                "scheduled_start_time": None,
                "monitor_hours": None,
                "platform": "custom",
                "platform_key": "custom"
            }
            
            # 创建Recording实例
            recording = Recording.from_dict(recording_data)
            
            # 添加到录制管理器
            await record_manager.add_recording(recording)
            
            # 开始监控录制
            await record_manager.start_monitor_recording(recording)
            
            # 更新UI - 创建录制卡片
            if hasattr(self.app_manager, 'record_card_manager'):
                card = await self.app_manager.record_card_manager.create_card(recording)
                # 如果当前页面是录制页面，添加卡片到UI
                if (hasattr(self.app_manager, 'current_page') and 
                    hasattr(self.app_manager.current_page, 'recording_card_area')):
                    self.app_manager.current_page.recording_card_area.content.controls.append(card)
                    self.app_manager.current_page.recording_card_area.update()
            
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
                        "status": recording.status_info
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