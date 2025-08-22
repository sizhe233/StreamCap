import asyncio
import os
import shutil
import subprocess
import time
from datetime import datetime
from typing import TypeVar

from ...messages import desktop_notify, message_pusher
from ...models.media.video_quality_model import VideoQuality
from ...models.recording.recording_status_model import RecordingStatus
from ...utils import utils
from ...utils.logger import logger
from ..media import ffmpeg_builders
from ..media.direct_downloader import DirectStreamDownloader
from ..platforms import platform_handlers
from ..platforms.platform_handlers import StreamData
from ..runtime.process_manager import BackgroundService

T = TypeVar("T")


class LiveStreamRecorder:
    DEFAULT_SEGMENT_TIME = "1800"
    DEFAULT_SAVE_FORMAT = "mp4"
    DEFAULT_QUALITY = VideoQuality.OD
    
    # 全局页面刷新控制锁（保留类级别的锁用于同步）
    _page_refresh_lock = asyncio.Lock()

    def __init__(self, app, recording, recording_info):
        self.app = app
        self.settings = app.settings
        self.recording = recording
        self.recording_info = recording_info
        self.subprocess_start_info = app.subprocess_start_up_info

        self.user_config = self.settings.user_config
        self.account_config = self.settings.accounts_config
        self.platform_key = self._get_info("platform_key")
        self.cookies = self.settings.cookies_config.get(self.platform_key)

        self.platform = self._get_info("platform")
        self.live_url = self._get_info("live_url")
        self.output_dir = self._get_info("output_dir")
        self.segment_record = self._get_info("segment_record", default=False)
        self.segment_time = self._get_info("segment_time", default=self.DEFAULT_SEGMENT_TIME)
        self.quality = self._get_info("quality", default=self.DEFAULT_QUALITY)
        self.save_format = self._get_info("save_format", default=self.DEFAULT_SAVE_FORMAT).lower()
        self.proxy = self.is_use_proxy()
        self.direct_downloader = None
        # 实例级别的页面刷新定时器，避免多个录制任务之间的冲突
        self._instance_refresh_timer = None
        os.makedirs(self.output_dir, exist_ok=True)
        self.app.language_manager.add_observer(self)
        self._ = {}
        self.load()

    def load(self):
        language = self.app.language_manager.language
        for key in ("recording_manager", "stream_manager"):
            self._.update(language.get(key, {}))
    
    def cleanup(self):
        """清理资源，包括取消定时器"""
        try:
            if self._instance_refresh_timer:
                self._instance_refresh_timer.cancel()
                self._instance_refresh_timer = None
                logger.debug(f"Cleaned up refresh timer for: {self.recording.streamer_name}")
        except Exception as e:
            logger.debug(f"Failed to cleanup refresh timer: {e}")
    
    def __del__(self):
        """析构函数，确保资源清理"""
        try:
            self.cleanup()
        except Exception:
            pass  # 忽略析构时的异常

    def safe_remove_recording_sync(self, record_name: str, error_message: str = "录制失败已从任务列表中移除", duration: int = 3000):
        """
        Synchronous version of recording removal to avoid async deadlocks
        """
        logger.info(f"Starting synchronous removal process for: {record_name}")
        
        try:
            # Step 1: Remove from backend task list (critical operation)
            try:
                from ...core.recording.record_manager import GlobalRecordingState
                # 改为非阻塞方式处理
                try:
                    # 使用异步任务处理，避免阻塞当前线程
                    async def async_remove():
                        async with GlobalRecordingState.lock:
                            if self.recording in GlobalRecordingState.recordings:
                                GlobalRecordingState.recordings.remove(self.recording)
                                logger.info(f"Removed recording from backend: {record_name}")
                            else:
                                logger.debug(f"Recording already removed from backend: {record_name}")
                    
                    asyncio.create_task(async_remove())
                except Exception as async_error:
                    logger.warning(f"Failed to schedule async removal: {async_error}")
                
                # Try to persist config, but don't block if it fails
                try:
                    asyncio.create_task(self.app.record_manager.persist_recordings())
                except Exception as persist_error:
                    logger.warning(f"Failed to schedule config persistence: {persist_error}")
                    
            except Exception as e:
                logger.warning(f"Failed to remove recording from backend: {e}")
            
            # Step 2-4: Try UI operations with immediate execution
            try:
                if self._is_page_connected():
                    # 立即执行UI移除操作，不使用异步任务
                    try:
                        # 直接调用移除UI卡片
                        self.app.page.run_task(self.app.record_card_manager.remove_recording_card, [self.recording])
                        logger.debug(f"Scheduled UI card removal for: {record_name}")
                    except Exception as e:
                        logger.warning(f"Failed to schedule UI card removal: {e}")
                    
                    # 发送pubsub通知
                    try:
                        self.app.page.pubsub.send_others_on_topic("delete", [self.recording])
                        logger.debug(f"Sent pubsub delete notification for: {record_name}")
                    except Exception as e:
                        logger.warning(f"Failed to send pubsub notification: {e}")
                    
                    # 显示通知
                    try:
                        self.app.page.run_task(self.app.snack_bar.show_snack_bar, f"{record_name} {error_message}", duration)
                        logger.debug(f"Scheduled notification for: {record_name}")
                    except Exception as e:
                        logger.warning(f"Failed to schedule notification: {e}")
                        
                    # 智能页面刷新控制，避免重复刷新
                    try:
                        if (hasattr(self.app, 'current_page') and 
                            self.app.current_page and 
                            hasattr(self.app.current_page, 'recording_card_area')):
                            
                            # 使用实例级别的定时器避免多个录制任务之间的冲突
                            def schedule_delayed_refresh():
                                try:
                                    # 取消当前实例之前的定时器
                                    if self._instance_refresh_timer:
                                        self._instance_refresh_timer.cancel()
                                        logger.debug(f"Cancelled previous refresh timer for: {record_name}")
                                    
                                    # 延迟检查并智能刷新
                                    def delayed_check():
                                        try:
                                            # 检查是否真的需要刷新页面
                                            needs_refresh = False
                                            
                                            # 检查是否有卡片移除失败
                                            if hasattr(self.app, 'record_card_manager') and self.app.record_card_manager:
                                                if self.recording.rec_id in self.app.record_card_manager.cards_obj:
                                                    needs_refresh = True
                                                    logger.debug(f"Card still exists after removal: {record_name}")
                                            
                                            # 避免强制刷新整个页面，改为智能UI更新
                                            if needs_refresh:
                                                logger.info(f"Performing smart UI update for: {record_name}")
                                                try:
                                                    # 只更新录制卡片区域，不刷新整个页面
                                                    if (hasattr(self.app, 'current_page') and 
                                                        self.app.current_page and 
                                                        hasattr(self.app.current_page, 'recording_card_area')):
                                                        self.app.current_page.recording_card_area.update()
                                                        logger.debug(f"Smart UI update completed for: {record_name}")
                                                    else:
                                                        logger.debug(f"Recording card area not available for update: {record_name}")
                                                except Exception as update_error:
                                                    logger.debug(f"Smart UI update failed: {update_error}")
                                            else:
                                                logger.debug(f"No UI update needed for: {record_name}")
                                                
                                        except Exception as e:
                                            logger.debug(f"Delayed refresh check failed: {e}")
                                        finally:
                                            # 清理当前实例的定时器引用
                                            self._instance_refresh_timer = None
                                    
                                    # 创建新的定时器（延迟1.5秒，给UI操作更多时间）
                                    import threading
                                    self._instance_refresh_timer = threading.Timer(1.5, delayed_check)
                                    self._instance_refresh_timer.start()
                                    logger.debug(f"Scheduled controlled page refresh check for: {record_name}")
                                    
                                except Exception as e:
                                    logger.debug(f"Failed to schedule controlled refresh: {e}")
                            
                            # 执行调度
                            schedule_delayed_refresh()
                            
                    except Exception as e:
                        logger.debug(f"Failed to setup controlled refresh: {e}")
                        
                    logger.debug(f"Completed UI operations for: {record_name}")
                else:
                    logger.debug(f"Page disconnected, skipping UI operations for: {record_name}")
            except Exception as ui_error:
                logger.warning(f"Failed to execute UI operations for {record_name}: {ui_error}")
            
            logger.info(f"Successfully completed removal process for: {record_name}")
            return True
                
        except Exception as e:
            logger.error(f"Critical error during removal process for {record_name}: {e}")
            return False

    async def _remove_ui_components_async(self, record_name: str, error_message: str, duration: int):
        """
        Handle UI removal operations asynchronously with individual timeouts
        """
        # Step 2: Remove UI card
        try:
            await asyncio.wait_for(
                self.app.record_card_manager.remove_recording_card([self.recording]),
                timeout=2.0
            )
            logger.info(f"Removed UI card: {record_name}")
        except asyncio.TimeoutError:
            logger.warning(f"UI card removal timed out for: {record_name}")
        except Exception as e:
            logger.warning(f"Failed to remove UI card: {e}")
        
        # Step 3: Send pubsub notification
        try:
            self.app.page.pubsub.send_others_on_topic("delete", [self.recording])
            # 不记录成功的pubsub通知，减少日志噪音
            pass
        except Exception as e:
            logger.warning(f"Failed to send pubsub notification: {e}")
        
        # Step 4: Show notification
        try:
            await asyncio.wait_for(
                self.app.snack_bar.show_snack_bar(f"{record_name} {error_message}", duration),
                timeout=1.0
            )
            # 不记录成功的通知显示，减少日志噪音
            pass
        except asyncio.TimeoutError:
            logger.warning(f"Notification display timed out for: {record_name}")
        except Exception as e:
            logger.warning(f"Failed to show notification: {e}")

    async def safe_remove_recording(self, record_name: str, error_message: str = "录制失败已从任务列表中移除", duration: int = 3000):
        """
        Safely remove a failed recording - now uses sync approach to avoid deadlocks
        """
        return self.safe_remove_recording_sync(record_name, error_message, duration)

    def _is_page_connected(self) -> bool:
        """Check if the page is still connected and responsive"""
        try:
            if not (hasattr(self.app, 'page') and 
                    self.app.page is not None and 
                    hasattr(self.app.page, 'update')):
                return False
                
            # Check if page is disconnected
            if getattr(self.app.page, '_disconnected', False):
                return False
                
            # Additional check for web pages that might be frozen
            if hasattr(self.app.page, 'web') and self.app.page.web:
                # For web pages, we assume they might be frozen if they've been inactive
                # This is a heuristic check
                return True  # We'll rely on timeouts to handle frozen pages
                
            return True
        except Exception as e:
            logger.debug(f"Page connection check failed: {e}")
            return False

    def _get_info(self, key: str, default: T = None) -> T:
        return self.recording_info.get(key, default) or default

    def is_use_proxy(self):
        default_proxy_platform = self.user_config.get("default_platform_with_proxy", "")
        proxy_list = default_proxy_platform.replace("，", ",").replace(" ", "").split(",")
        if self.user_config.get("enable_proxy") and self.platform_key in proxy_list:
            self.proxy = self.user_config.get("proxy_address")
            return self.proxy

    def _get_filename(self, stream_info: StreamData) -> str:
        live_title = None
        stream_info.title = utils.clean_name(stream_info.title, None)
        if self.user_config.get("filename_includes_title") and stream_info.title:
            stream_info.title = self._clean_and_truncate_title(stream_info.title)
            live_title = stream_info.title

        if self.recording.streamer_name and self.recording.streamer_name != self._["live_room"]:
            stream_info.anchor_name = self.recording.streamer_name
        else:
            stream_info.anchor_name = utils.clean_name(stream_info.anchor_name, self._["live_room"])

        now = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())

        custom_template = self.user_config.get("custom_filename_template")
        if custom_template:
            filename = custom_template
            filename = filename.replace("{anchor_name}", stream_info.anchor_name or "")
            filename = filename.replace("{title}", live_title or "")
            filename = filename.replace("{time}", now)
            filename = filename.replace("{platform}", stream_info.platform or "")

            while "__" in filename:
                filename = filename.replace("__", "_")

            filename = filename.strip("_")

            if not filename:
                full_filename = "_".join([i for i in (stream_info.anchor_name, live_title, now) if i])
            else:
                full_filename = filename
        else:
            full_filename = "_".join([i for i in (stream_info.anchor_name, live_title, now) if i])

        return full_filename

    def _get_output_dir(self, stream_info: StreamData) -> str:
        if self.recording.recording_dir and self.user_config.get("folder_name_time"):
            current_date = datetime.today().strftime("%Y-%m-%d")
            if current_date not in self.recording.recording_dir:
                self.recording.recording_dir = None

        if self.recording.recording_dir:
            return self.recording.recording_dir

        now = datetime.today().strftime("%Y-%m-%d_%H-%M-%S")
        output_dir = self.output_dir.rstrip("/").rstrip("\\")
        if self.user_config.get("folder_name_platform"):
            output_dir = os.path.join(output_dir, stream_info.platform)
        if self.user_config.get("folder_name_author"):
            # 清理主播名字，避免Windows文件系统不支持的字符
            clean_anchor_name = utils.clean_name(stream_info.anchor_name, "Unknown")
            output_dir = os.path.join(output_dir, clean_anchor_name)
        if self.user_config.get("folder_name_time"):
            output_dir = os.path.join(output_dir, now[:10])
        if self.user_config.get("folder_name_title") and stream_info.title:
            live_title = self._clean_and_truncate_title(stream_info.title)
            if self.user_config.get("folder_name_time"):
                clean_anchor_name = utils.clean_name(stream_info.anchor_name, "Unknown")
                output_dir = os.path.join(output_dir, f"{live_title}_{clean_anchor_name}")
            else:
                output_dir = os.path.join(output_dir, f"{now[:10]}_{live_title}")
        os.makedirs(output_dir, exist_ok=True)
        self.recording.recording_dir = output_dir
        self.app.page.run_task(self.app.record_manager.persist_recordings)
        return output_dir

    def _get_save_path(self, filename: str, use_direct_download: bool = False) -> str:
        suffix = self.save_format
        suffix = "_%03d." + suffix if self.segment_record and not use_direct_download else "." + suffix
        save_file_path = os.path.join(self.output_dir, filename + suffix).replace(" ", "_")
        return save_file_path.replace("\\", "/")

    @staticmethod
    def _clean_and_truncate_title(title: str) -> str | None:
        if not title:
            return None
        cleaned_title = title[:30].replace("，", ",").replace(" ", "")
        return cleaned_title

    @property
    def is_flv_preferred_platform(self):
        return self.platform_key in {"douyin", "tiktok"}

    def _select_source_url(self, stream_info: StreamData):
        if (
                self.user_config.get("default_live_source") != "HLS"
                and self.is_flv_preferred_platform
        ):
            codec = utils.get_query_params(stream_info.flv_url, "codec")
            if codec and codec[0] == 'h265':
                logger.warning("FLV is not supported for h265 codec, use HLS source instead")
            else:
                return stream_info.flv_url

        return stream_info.record_url

    def _get_record_url(self, stream_info: StreamData):

        url = self._select_source_url(stream_info)

        http_record_list = ["shopee", "migu"]
        if self.user_config.get("force_https_recording") and url.startswith("http://"):
            url = url.replace("http://", "https://")

        if self.platform_key in http_record_list:
            url = url.replace("https://", "http://")
        return url

    def set_preview_url(self, stream_info: StreamData):
        self.recording.preview_url = stream_info.m3u8_url or stream_info.flv_url

    def _get_record_format(self, stream_info: StreamData):
        use_flv_record = ["shopee"]
        if stream_info.flv_url:
            if self.platform_key in use_flv_record or self.recording.flv_use_direct_download:
                self.save_format = "flv"
                self.recording.record_format = self.save_format
                self.recording.segment_record = False
                return self.save_format, True

            elif self.save_format == "flv":
                codec = utils.get_query_params(stream_info.flv_url, "codec")
                if codec and codec[0] == 'h265':
                    logger.warning("FLV is not supported for h265 codec, use TS format instead")
                    self.save_format = "ts"

        return self.save_format, False

    async def fetch_stream(self) -> StreamData:
        logger.info(f"Live URL: {self.live_url}")
        logger.info(f"Use Proxy: {self.proxy or None}")
        self.recording.use_proxy = bool(self.proxy)
        handler = platform_handlers.get_platform_handler(
            live_url=self.live_url,
            proxy=self.proxy,
            cookies=self.cookies,
            record_quality=self.quality,
            platform=self.platform,
            username=self.account_config.get(self.platform_key, {}).get("username"),
            password=self.account_config.get(self.platform_key, {}).get("password"),
            account_type=self.account_config.get(self.platform_key, {}).get("account_type")
        )

        stream_info = await handler.get_stream_info(self.live_url)
        self.recording.is_checking = False
        return stream_info

    async def start_recording(self, stream_info: StreamData):
        """
        Construct ffmpeg recording parameters and start recording
        """

        self.save_format, use_direct_download = self._get_record_format(stream_info)
        filename = self._get_filename(stream_info)
        self.output_dir = self._get_output_dir(stream_info)
        save_path = self._get_save_path(filename, use_direct_download)
        logger.info(f"Save Path: {save_path}")
        self.recording.recording_dir = os.path.dirname(save_path)
        os.makedirs(self.recording.recording_dir, exist_ok=True)
        record_url = self._get_record_url(stream_info)
        self.set_preview_url(stream_info)

        if use_direct_download:
            logger.info(f"Use Direct Downloader to Download FLV Stream: {record_url}")
            headers = {}
            header_params = self.get_headers_params(record_url, self.platform_key)
            if header_params:
                key, value = header_params.split(":", 1)
                headers[key] = value

            # Create simple status callback (non-blocking)
            def status_callback(status: str):
                """简单的状态回调，处理状态变化和速度更新"""
                try:
                    # 检查是否是速度信息
                    if status.startswith("速度: "):
                        speed_value = status.replace("速度: ", "")
                        old_speed = self.recording.speed
                        if speed_value != old_speed:
                            self.recording.speed = speed_value
                            # 双重更新机制：确保速度更新的可靠性
                            try:
                                # 主要方案：通过pubsub发送更新
                                self.app.page.pubsub.send_others_on_topic("update", self.recording)
                                
                                # 备用方案：直接调用UI更新（解决PubSub在异步任务中的限制）
                                if hasattr(self.app, 'record_card_manager') and self.app.record_card_manager:
                                    self.app.page.run_task(self.app.record_card_manager.update_card, self.recording)
                                
                                logger.debug(f"Speed updated via callback: {old_speed} -> {speed_value}")
                            except Exception as e:
                                logger.debug(f"Failed to update speed via callback: {e}")
                    else:
                        # 处理普通状态信息
                        if status != self.recording.status_info:
                            old_status = self.recording.status_info
                            self.recording.status_info = status
                            # 状态变化时立即更新UI
                            try:
                                self.app.page.pubsub.send_others_on_topic("update", self.recording)
                                logger.info(f"Status updated via callback: {old_status} -> {status}")
                            except Exception as e:
                                logger.debug(f"Failed to update status via callback: {e}")
                except Exception as e:
                    logger.debug(f"Error in status callback: {e}")

            # 从用户配置获取重连参数
            max_retries = self.user_config.get("direct_download_max_retries", 3)
            retry_delay = self.user_config.get("direct_download_retry_delay", 5)
            
            # 自定义流断流重连策略参数
            custom_stream_buffer_time = self.user_config.get("custom_stream_buffer_time", 60)  # 缓冲等待时间，默认60秒
            custom_stream_retry_interval = self.user_config.get("custom_stream_retry_interval", 10)  # 重连间隔，默认10秒
            max_concurrent_downloads = self.user_config.get("max_concurrent_custom_streams", 8)  # 最大并发自定义流数，默认8
            
            self.direct_downloader = DirectStreamDownloader(
                record_url=record_url,
                save_path=save_path,
                headers=headers,
                proxy=self.proxy,
                status_callback=status_callback,
                max_retries=max_retries,
                retry_delay=retry_delay,
                custom_stream_buffer_time=custom_stream_buffer_time,
                custom_stream_retry_interval=custom_stream_retry_interval,
                max_concurrent_downloads=max_concurrent_downloads
            )
            
            # 如果录制任务已有start_time，同步给下载器
            if hasattr(self.recording, 'start_time') and self.recording.start_time:
                self.direct_downloader.start_time = self.recording.start_time.timestamp()
                logger.info(f"Synced start time from recording: {self.recording.start_time}")

            self.app.page.run_task(
                self.start_direct_download,
                stream_info.anchor_name,
                self.live_url,
                record_url,
                save_path,
                self.save_format,
                self.user_config.get("custom_script_command")
            )
        else:
            ffmpeg_builder = ffmpeg_builders.create_builder(
                self.save_format,
                record_url=record_url,
                proxy=self.proxy,
                segment_record=self.segment_record,
                segment_time=self.segment_time,
                full_path=save_path,
                headers=self.get_headers_params(record_url, self.platform_key)
            )
            ffmpeg_command = ffmpeg_builder.build_command()
            self.app.page.run_task(
                self.start_ffmpeg,
                stream_info.anchor_name,
                self.live_url,
                record_url,
                ffmpeg_command,
                self.save_format,
                self.user_config.get("custom_script_command")
            )

    async def start_ffmpeg(
            self,
            record_name: str,
            live_url: str,
            record_url: str,
            ffmpeg_command: list,
            save_type: str,
            script_command: str | None = None
    ) -> bool:
        """
        The child process executes ffmpeg for recording
        """

        try:
            save_file_path = ffmpeg_command[-1]

            process = await asyncio.create_subprocess_exec(
                *ffmpeg_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                startupinfo=self.subprocess_start_info
            )

            self.app.add_ffmpeg_process(process)
            self.recording.status_info = RecordingStatus.RECORDING
            self.recording.record_url = record_url
            logger.info(f"Recording in Progress: {live_url}")
            logger.log("STREAM", f"Recording Stream URL: {record_url}")

            # Start speed monitoring task (unified method)
            speed_task = asyncio.create_task(self._monitor_file_speed(save_file_path, process))

            while True:
                if not self.recording.is_recording or not self.app.recording_enabled:
                    logger.info(f"Preparing to End Recording: {live_url}")
                    
                    # Cancel speed monitoring
                    speed_task.cancel()

                    if os.name == "nt":
                        if process.stdin:
                            process.stdin.write(b"q")
                            await process.stdin.drain()
                            await asyncio.sleep(5)
                    else:
                        import signal
                        process.send_signal(signal.SIGINT)
                        # process.terminate()
                        await asyncio.sleep(5)

                    if process.stdin:
                        process.stdin.close()

                    try:
                        await asyncio.wait_for(process.wait(), timeout=15.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"FFmpeg process did not exit gracefully, forcing termination: {live_url}")
                        process.kill()
                        await process.wait()

                if process.returncode is not None:
                    logger.info(f"Exit loop recording (normal 0 | abnormal 1): code={process.returncode}, {live_url}")
                    speed_task.cancel()
                    break

                await asyncio.sleep(1)

            return_code = process.returncode
            safe_return_code = [0, 255]
            stdout, stderr = await process.communicate()
            if return_code not in safe_return_code and stderr:
                logger.error(f"FFmpeg Stderr Output: {str(stderr.decode()).splitlines()[0]}")
                self.recording.status_info = RecordingStatus.RECORDING_ERROR

                # Check if this is a 404 or similar critical error that should remove the task
                stderr_output = str(stderr.decode()).lower()
                is_critical_error = any(error in stderr_output for error in ['404', 'not found', 'connection refused', 'no route to host'])

                try:
                    self.app.record_manager.stop_recording(self.recording)
                    
                    if is_critical_error:
                        # For critical errors like 404, remove from task list but keep downloaded files
                        logger.info(f"Removing failed recording from task list due to critical error: {record_name}")
                        
                        # Execute removal immediately without blocking
                        try:
                            self.safe_remove_recording_sync(record_name)
                        except Exception as e:
                            logger.error(f"Failed to remove recording {record_name}: {e}")
                    else:
                        # For other errors, just update the status
                        self.app.page.run_task(self.app.record_card_manager.update_card, self.recording)
                        self.app.page.pubsub.send_others_on_topic("update", self.recording)
                        self.app.page.run_task(self.app.snack_bar.show_snack_bar,
                                             record_name + " " + self._["record_stream_error"], 2000)
                except Exception as e:
                    logger.debug(f"Failed to handle recording error: {e}")

            if return_code in safe_return_code:
                # For custom streams (FLV/M3U8), automatically remove task after completion
                # since these are typically one-time URLs that won't restart
                if self.platform_key == "custom" and self.recording.monitor_status:
                    logger.info(f"Custom stream completed, removing task: {record_name}")
                    self.recording.monitor_status = False
                    self.recording.status_info = RecordingStatus.CUSTOM_STREAM_COMPLETED
                    
                    # Auto-remove custom stream task after completion
                    try:
                        logger.info(f"Auto-removing completed custom stream task: {record_name}")
                        self.safe_remove_recording_sync(record_name, "自定义流录制完成，任务已自动移除")
                        return  # Exit early since task is removed
                    except Exception as e:
                        logger.error(f"Failed to auto-remove custom stream task {record_name}: {e}")
                
                if self.recording.monitor_status:
                    self.recording.status_info = RecordingStatus.MONITORING
                    display_title = self.recording.title
                else:
                    self.recording.status_info = RecordingStatus.STOPPED_MONITORING
                    display_title = self.recording.display_title

                self.recording.live_title = None
                if not self.recording.is_recording:
                    logger.success(f"Live recording has stopped: {record_name}")
                else:

                    logger.success(f"Live recording completed: {record_name}")
                    self.app.page.run_task(self.end_message_push)
                    self.recording.is_recording = False
                try:
                    self.recording.update({"display_title": display_title})
                    self.app.page.run_task(self.app.record_card_manager.update_card, self.recording)
                    self.app.page.pubsub.send_others_on_topic("update", self.recording)
                    if not self.app.recording_enabled:
                        self.recording.status_info = RecordingStatus.NOT_RECORDING_SPACE
                        self.app.page.run_task(self.stop_recording_notify)

                except Exception as e:
                    logger.debug(f"Failed to update UI: {e}")

                if self.user_config.get("convert_to_mp4") and self.save_format == "ts":
                    if self.segment_record:
                        file_paths = utils.get_file_paths(os.path.dirname(save_file_path))
                        prefix = os.path.basename(save_file_path).rsplit("_", maxsplit=1)[0]
                        for path in file_paths:
                            if prefix in path:
                                try:
                                    self.app.page.run_task(
                                        self.converts_mp4, path, self.user_config["delete_original"]
                                    )
                                except Exception as e:
                                    logger.error(f"Failed to convert video: {e}")
                                    await self.converts_mp4(path, self.user_config["delete_original"])
                    else:
                        try:
                            self.app.page.run_task(
                                self.converts_mp4, save_file_path, self.user_config["delete_original"]
                            )
                        except Exception as e:
                            logger.error(f"Failed to convert video: {e}")
                            await self.converts_mp4(save_file_path, self.user_config["delete_original"])

                if self.user_config.get("execute_custom_script") and script_command:
                    logger.info("Prepare a direct script in the background")
                    try:
                        self.app.page.run_task(
                            self.custom_script_execute,
                            script_command,
                            record_name,
                            save_file_path,
                            save_type,
                            self.segment_record,
                            self.user_config.get("convert_to_mp4")
                        )
                        logger.success("Successfully added script execution")
                    except Exception as e:
                        logger.error(f"Failed to execute custom script: {e}")
                        await self.custom_script_execute(
                            script_command,
                            record_name,
                            save_file_path,
                            save_type,
                            self.segment_record,
                            self.user_config.get("convert_to_mp4")
                        )

        except Exception as e:
            logger.error(f"An error occurred during the subprocess execution: {e}")
            self.recording.status_info = RecordingStatus.RECORDING_ERROR

            # 检查是否为需要移除任务的关键错误
            error_message = str(e).lower()
            # 扩展关键错误检测，但更加保守
            critical_errors = [
                '404', 'not found', 'connection refused', 'no route to host',
                'stream not found', 'invalid url', 'forbidden', 'unauthorized',
                'stream offline permanently', 'account suspended'
            ]
            is_critical_error = any(error in error_message for error in critical_errors)
            
            # 记录详细的错误信息用于调试
            logger.error(f"Recording error for {record_name}: {error_message}")
            logger.info(f"Critical error check result: {is_critical_error}")

            try:
                self.app.record_manager.stop_recording(self.recording)
                
                if is_critical_error:
                    # For critical errors, remove from task list but keep downloaded files
                    logger.info(f"Removing failed recording from task list due to critical error: {record_name}")
                    
                    # Execute removal immediately without blocking
                    try:
                        self.safe_remove_recording_sync(record_name, "录制失败已从任务列表中移除", 4000)
                    except Exception as e:
                        logger.error(f"Failed to remove recording {record_name}: {e}")
                else:
                    # For other errors, just update the status
                    self.app.page.run_task(self.app.record_card_manager.update_card, self.recording)
                    self.app.page.pubsub.send_others_on_topic("update", self.recording)
                    self.app.page.run_task(self.app.snack_bar.show_snack_bar,
                                         record_name + " " + self._["no_ffmpeg_tip"], 4000)
            except Exception as e:
                logger.debug(f"Failed to handle recording error: {e}")
            return False
        finally:
            self.recording.record_url = None

        return True

    async def _monitor_ffmpeg_speed(self, process, save_file_path: str):
        """Monitor FFmpeg recording speed by checking file size"""
        try:
            last_size = 0
            last_time = time.time()
            
            while not process.returncode and self.recording.is_recording:
                await asyncio.sleep(2)  # Check every 2 seconds
                
                try:
                    if os.path.exists(save_file_path):
                        current_size = os.path.getsize(save_file_path)
                        current_time = time.time()
                        
                        if current_time > last_time:
                            bytes_diff = current_size - last_size
                            time_diff = current_time - last_time
                            
                            if time_diff > 0 and bytes_diff >= 0:
                                bytes_per_sec = bytes_diff / time_diff
                                if bytes_per_sec >= 1024 * 1024:  # MB/s
                                    self.recording.speed = f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"
                                elif bytes_per_sec >= 1024:  # KB/s
                                    self.recording.speed = f"{bytes_per_sec / 1024:.0f} KB/s"
                                else:  # B/s
                                    self.recording.speed = f"{bytes_per_sec:.0f} B/s"
                            else:
                                self.recording.speed = "0 B/s"
                                
                            # Update UI
                            try:
                                self.app.page.run_task(self.app.record_card_manager.update_card, self.recording)
                            except Exception as e:
                                logger.debug(f"Failed to update speed in UI: {e}")
                            
                            last_size = current_size
                            last_time = current_time
                    else:
                        # File doesn't exist yet, set speed to 0
                        self.recording.speed = "0 B/s"
                        try:
                            self.app.page.run_task(self.app.record_card_manager.update_card, self.recording)
                        except Exception as e:
                            logger.debug(f"Failed to update speed in UI: {e}")
                    
                except (OSError, FileNotFoundError):
                    # File might not exist yet or be temporarily unavailable
                    self.recording.speed = "0 B/s"
                    try:
                        self.app.page.run_task(self.app.record_card_manager.update_card, self.recording)
                    except Exception as e:
                        logger.debug(f"Failed to update speed in UI: {e}")
                    
        except asyncio.CancelledError:
            logger.debug("FFmpeg speed monitoring cancelled")
            # Set speed to 0 when cancelled
            self.recording.speed = "0 B/s"
            try:
                self.app.page.run_task(self.app.record_card_manager.update_card, self.recording)
            except Exception as e:
                logger.debug(f"Failed to update speed in UI: {e}")
        except Exception as e:
            logger.debug(f"Error in FFmpeg speed monitoring: {e}")
            self.recording.speed = "0 B/s"
            try:
                self.app.page.run_task(self.app.record_card_manager.update_card, self.recording)
            except Exception as e:
                logger.debug(f"Failed to update speed in UI: {e}")

    async def converts_mp4(self, converts_file_path: str, is_original_delete: bool = True) -> None:
        """Asynchronous transcoding method, can be added to the background service to continue execution"""
        if not self.app.recording_enabled:
            logger.info(f"Application is closing, adding transcoding task to background service: {converts_file_path}")
            BackgroundService.get_instance().add_task(
                self.converts_mp4_sync, converts_file_path, is_original_delete
            )
            return

        # Otherwise, execute transcoding normally
        await self._do_converts_mp4(converts_file_path, is_original_delete)

    def converts_mp4_sync(self, converts_file_path: str, is_original_delete: bool = True) -> None:
        """Synchronous version of the transcoding method, used for background service"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._do_converts_mp4(converts_file_path, is_original_delete))
        finally:
            loop.close()

    async def _do_converts_mp4(self, converts_file_path: str, is_original_delete: bool = True) -> None:
        """Actual execution method for transcoding"""
        converts_success = False
        save_path = None
        try:
            converts_file_path = converts_file_path.replace("\\", "/")
            if os.path.exists(converts_file_path) and os.path.getsize(converts_file_path) > 0:
                save_path = converts_file_path.rsplit(".", maxsplit=1)[0] + ".mp4"
                ffmpeg_command = [
                    "ffmpeg",
                    "-i", converts_file_path,
                    "-c:v", "copy",
                    "-c:a", "copy",
                    "-f", "mp4",
                    save_path
                ]
                process = await asyncio.create_subprocess_exec(
                    *ffmpeg_command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    startupinfo=self.subprocess_start_info
                )

                self.app.add_ffmpeg_process(process)
                task = asyncio.create_task(process.communicate())
                _, stderr = await task
                if process.returncode == 0:
                    converts_success = True
                    logger.info(f"Video transcoding completed: {save_path}")
                else:
                    logger.error(
                        f"Video transcoding failed! Error message: {stderr.decode() if stderr else 'Unknown error'}")

        except subprocess.CalledProcessError as e:
            logger.error(f"Video transcoding failed! Error message: {e.output.decode()}")

        try:
            if converts_success:
                if is_original_delete:
                    await asyncio.sleep(1)
                    if os.path.exists(converts_file_path):
                        os.remove(converts_file_path)
                    logger.info(f"Delete Original File: {converts_file_path}")
                else:
                    converts_dir = f"{os.path.dirname(save_path)}/original"
                    os.makedirs(converts_dir, exist_ok=True)
                    shutil.move(converts_file_path, converts_dir)
                    logger.info(f"Move Transcoding Files: {converts_file_path}")

        except subprocess.CalledProcessError as e:
            logger.error(f"Error occurred during conversion: {e}")
        except Exception as e:
            logger.error(f"An unknown error occurred: {e}")

    async def custom_script_execute(
            self,
            script_command: str,
            record_name: str,
            save_file_path: str,
            save_type: str,
            split_video_by_time: bool,
            converts_to_mp4: bool
    ):
        from ..runtime.process_manager import BackgroundService

        if "python" in script_command:
            params = [
                f'--record_name "{record_name}"',
                f'--save_file_path "{save_file_path}"',
                f"--save_type {save_type}--split_video_by_time {split_video_by_time}",
                f"--converts_to_mp4 {converts_to_mp4}"
            ]
        else:
            params = [
                f'"{record_name.split(" ", maxsplit=1)[-1]}"',
                f'"{save_file_path}"',
                save_type,
                f"split_video_by_time: {split_video_by_time}",
                f"converts_to_mp4: {converts_to_mp4}"
            ]
        script_command = script_command.strip() + " " + " ".join(params)

        if not self.app.recording_enabled:
            logger.info("Application is closing, adding script execution task to background service")
            BackgroundService.get_instance().add_task(self.run_script_sync, script_command)
        else:
            self.app.page.run_task(self.run_script_async, script_command)

        logger.success("Script command execution initiated!")

    def run_script_sync(self, command: str) -> None:
        """Synchronous version of the script execution method, used for background service"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.run_script_async(command))
        finally:
            loop.close()

    async def run_script_async(self, command: str) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                *command.split(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                startupinfo=self.subprocess_start_info,
                text=True
            )

            stdout, stderr = await process.communicate()

            if stdout:
                logger.info(stdout.splitlines()[0])
            if stderr:
                logger.error(stderr.splitlines()[0])

            if process.returncode != 0:
                logger.info(f"Custom Script process exited with return code {process.returncode}")

        except PermissionError:
            logger.error(
                "Script has no execution permission!, If it is a Linux environment, "
                "please first execute: chmod+x your_script.sh to grant script executable permission"
            )
        except OSError:
            logger.error("Please add `#!/bin/bash` at the beginning of your bash script file.")
        except Exception as e:
            logger.error(f"An error occurred: {e}")

    @staticmethod
    def get_headers_params(live_url, platform_key):
        live_domain = "/".join(live_url.split("/")[0:3])
        record_headers = {
            "pandalive": "origin:https://www.pandalive.co.kr",
            "winktv": "origin:https://www.winktv.co.kr",
            "popkontv": "origin:https://www.popkontv.com",
            "flextv": "origin:https://www.flextv.co.kr",
            "qiandurebo": "referer:https://qiandurebo.com",
            "17live": "referer:https://17.live/en/live/6302408",
            "lang": "referer:https://www.lang.live",
            "shopee": "origin:" + live_domain,
            "blued": "referer:https://app.blued.cn",
        }
        return record_headers.get(platform_key)

    async def start_direct_download(
            self,
            record_name: str,
            live_url: str,
            record_url: str,
            save_file_path: str,
            save_type: str,
            script_command: str | None = None
    ) -> bool:
        """
        Use the direct downloader to download the live stream
        """
        try:
            await self.direct_downloader.start_download()

            self.recording.status_info = RecordingStatus.RECORDING
            self.recording.record_url = record_url
            logger.info(f"Direct Downloading: {live_url}")
            logger.log("STREAM", f"Direct Download Stream URL: {record_url}")
            
            # 开始录制时立即更新UI状态
            try:
                self.app.page.pubsub.send_others_on_topic("update", self.recording)
            except Exception as e:
                logger.debug(f"Failed to update UI for recording start: {e}")

            # 注意：不再在这里启动速度监控任务，因为direct_downloader内部已经有速度监控
            # 直接下载器将通过status_callback回调机制更新速度
            
            download_completed_successfully = False
            download_failed = False
            
            while True:
                if not self.recording.is_recording or not self.app.recording_enabled:
                    logger.info(f"Prepare to end direct download: {live_url}")
                    await self.direct_downloader.stop_download()
                    break

                # 检查是否正在重连
                if hasattr(self.direct_downloader, 'is_reconnecting') and self.direct_downloader.is_reconnecting:
                    if self.recording.status_info != RecordingStatus.MONITORING:
                        self.recording.status_info = RecordingStatus.MONITORING
                        logger.info(f"Direct download reconnecting: {record_name}")
                        # 状态变化时立即更新UI
                        try:
                            self.app.page.pubsub.send_others_on_topic("update", self.recording)
                        except Exception as e:
                            logger.debug(f"Failed to update UI for reconnecting status: {e}")
                elif self.recording.status_info == RecordingStatus.MONITORING and not self.direct_downloader.is_reconnecting:
                    # 重连成功，恢复录制状态
                    self.recording.status_info = RecordingStatus.RECORDING
                    logger.info(f"Direct download reconnected successfully: {record_name}")
                    # 状态变化时立即更新UI
                    try:
                        self.app.page.pubsub.send_others_on_topic("update", self.recording)
                    except Exception as e:
                        logger.debug(f"Failed to update UI for reconnected status: {e}")

                await asyncio.sleep(1)

                if self.direct_downloader.download_task and self.direct_downloader.download_task.done():
                    # 获取下载任务的异常信息
                    task_exception = None
                    try:
                        task_exception = self.direct_downloader.download_task.exception()
                    except Exception:
                        pass
                    
                    # 对于直播流，download_task.done()通常意味着连接中断，而不是正常完成
                    # 只有在手动停止的情况下才算正常完成
                    if self.direct_downloader.stop_event.is_set() and self.direct_downloader.total_bytes > 0:
                        download_completed_successfully = True
                        logger.info(f"Direct download completed successfully (manually stopped): {record_name}, bytes: {self.direct_downloader.total_bytes}")
                    elif task_exception is not None:
                        # 有异常发生，检查是否为关键错误
                        error_msg = str(task_exception).lower()
                        is_critical_error = any(error in error_msg for error in ['404', 'not found', 'connection refused', 'no route to host', 'stream failed'])
                        
                        if is_critical_error:
                            logger.warning(f"Critical download error detected: {task_exception}")
                            download_failed = True
                        else:
                            # 非关键错误，可能是临时网络问题，不自动移除任务
                            logger.warning(f"Non-critical download error, keeping task active: {task_exception}")
                            self.recording.status_info = RecordingStatus.MONITORING
                            break
                    else:
                        # 连接正常结束或中断但没有关键异常
                        # 对于自定义流，检查用户配置是否需要自动删除
                        if self.platform_key == "custom":
                            auto_remove_enabled = self.user_config.get("auto_remove_custom_stream_tasks", True)
                            if auto_remove_enabled:
                                if self.direct_downloader.total_bytes > 0:
                                    logger.info(f"Custom stream completed/interrupted after downloading {self.direct_downloader.total_bytes} bytes. Auto-removing task: {record_name}")
                                    # 设置为完成状态，触发自动删除逻辑
                                    download_completed_successfully = True
                                else:
                                    logger.info(f"Custom stream completed/interrupted with no data received. Auto-removing task: {record_name}")
                                    # 设置为失败状态，触发自动删除逻辑
                                    download_failed = True
                                break
                            else:
                                if self.direct_downloader.total_bytes > 0:
                                    logger.info(f"Custom stream completed/interrupted after downloading {self.direct_downloader.total_bytes} bytes. Keeping task active (auto-removal disabled): {record_name}")
                                else:
                                    logger.info(f"Custom stream completed/interrupted with no data received. Keeping task active (auto-removal disabled): {record_name}")
                                self.recording.status_info = RecordingStatus.MONITORING
                                break
                        else:
                            # 对于平台流，保持原有逻辑，等待重连
                            if self.direct_downloader.total_bytes > 0:
                                logger.info(f"Platform stream completed/interrupted after downloading {self.direct_downloader.total_bytes} bytes. Keeping task active for potential reconnection: {record_name}")
                            else:
                                logger.info(f"Platform stream completed/interrupted with no data received. Keeping task active: {record_name}")
                            self.recording.status_info = RecordingStatus.MONITORING
                            break
                    
                    break

            # Handle different completion scenarios
            if download_failed:
                logger.warning(f"Direct Downloading Failed: {record_name}")
                self.recording.status_info = RecordingStatus.RECORDING_ERROR
                self.recording.is_recording = False
                
                # For custom streams, automatically remove failed tasks
                try:
                    self.app.record_manager.stop_recording(self.recording)
                    
                    # For custom streams, check user preference for auto-removal of failed tasks
                    if self.platform_key == "custom":
                        auto_remove_enabled = self.user_config.get("auto_remove_custom_stream_tasks", True)
                        if auto_remove_enabled:
                            logger.info(f"Auto-removing failed custom stream task: {record_name}")
                            try:
                                self.safe_remove_recording_sync(record_name, "自定义流录制失败，任务已自动移除")
                            except Exception as e:
                                logger.error(f"Failed to auto-remove failed custom stream task {record_name}: {e}")
                        else:
                            logger.info(f"Custom stream failed, keeping task active (auto-removal disabled): {record_name}")
                    else:
                        # For platform streams, just remove from task list but keep downloaded files
                        logger.info(f"Removing failed recording from task list: {record_name}")
                        try:
                            self.safe_remove_recording_sync(record_name, "录制失败已从任务列表中移除")
                        except Exception as e:
                            logger.error(f"Failed to remove recording {record_name}: {e}")
                    
                except Exception as e:
                    logger.debug(f"Failed to remove failed recording from task list: {e}")
                
                return False
            
            elif download_completed_successfully:
                logger.success(f"Direct Downloading Completed: {record_name}")
                self.app.page.run_task(self.end_message_push)
                self.recording.is_recording = False
                
                # For custom streams (FLV/M3U8), check user preference for auto-removal
                if self.platform_key == "custom":
                    self.recording.monitor_status = False
                    self.recording.status_info = RecordingStatus.CUSTOM_STREAM_COMPLETED
                    
                    # Check user configuration for auto-removal
                    auto_remove_enabled = self.user_config.get("auto_remove_custom_stream_tasks", True)
                    if auto_remove_enabled:
                        logger.info(f"Custom stream completed, auto-removing task: {record_name}")
                        try:
                            self.safe_remove_recording_sync(record_name, "自定义流录制完成，任务已自动移除")
                            return  # Exit early since task is removed
                        except Exception as e:
                            logger.error(f"Failed to auto-remove custom stream task {record_name}: {e}")
                    else:
                        logger.info(f"Custom stream completed, keeping task active (auto-removal disabled): {record_name}")
                    
            else:
                logger.success(f"Direct Downloading Stopped: {record_name}")

            # Set appropriate status based on monitor settings
            if self.recording.monitor_status:
                self.recording.status_info = RecordingStatus.MONITORING
                display_title = self.recording.title
            else:
                self.recording.status_info = RecordingStatus.STOPPED_MONITORING
                display_title = self.recording.display_title

            self.recording.live_title = None

            try:
                self.recording.update({"display_title": display_title})
                # 只通过pubsub机制更新UI，避免双重更新和绕过频率限制
                self.app.page.pubsub.send_others_on_topic("update", self.recording)
                if not self.app.recording_enabled:
                    self.recording.status_info = RecordingStatus.NOT_RECORDING_SPACE
                    self.app.page.run_task(self.stop_recording_notify)

            except Exception as e:
                logger.debug(f"Failed to update UI: {e}")

            if self.user_config.get("execute_custom_script") and script_command and download_completed_successfully:
                logger.info("Prepare to execute custom script in the background")
                try:
                    self.app.page.run_task(
                        self.custom_script_execute,
                        script_command,
                        record_name,
                        save_file_path,
                        save_type,
                        False,
                        False
                    )
                    logger.success("Successfully added script execution")
                except Exception as e:
                    logger.error(f"Failed to execute custom script: {e}")
                    await self.custom_script_execute(
                        script_command,
                        record_name,
                        save_file_path,
                        save_type,
                        False,
                        False
                    )

            return download_completed_successfully

        except Exception as e:
            logger.error(f"Error occurred during direct download: {e}")
            self.recording.status_info = RecordingStatus.RECORDING_ERROR
            self.recording.is_recording = False

            # 检查是否为需要移除任务的关键错误
            error_message = str(e).lower()
            # 使用与FFmpeg相同的关键错误检测逻辑
            critical_errors = [
                '404', 'not found', 'connection refused', 'no route to host',
                'stream not found', 'invalid url', 'forbidden', 'unauthorized',
                'stream offline permanently', 'account suspended'
            ]
            is_critical_error = any(error in error_message for error in critical_errors)
            
            # 记录详细的错误信息用于调试
            logger.error(f"Direct download error for {record_name}: {error_message}")
            logger.info(f"Critical error check result: {is_critical_error}")

            try:
                self.app.record_manager.stop_recording(self.recording)
                
                if is_critical_error:
                    # For critical errors, remove from task list but keep downloaded files
                    logger.info(f"Removing failed recording from task list due to critical error: {record_name}")
                    
                    # Execute removal immediately without blocking
                    try:
                        self.safe_remove_recording_sync(record_name)
                    except Exception as e:
                        logger.error(f"Failed to remove recording {record_name}: {e}")
                else:
                    # For other errors, just update the status
                    self.app.page.run_task(self.app.record_card_manager.update_card, self.recording)
                    self.app.page.pubsub.send_others_on_topic("update", self.recording)
                    self.app.page.run_task(self.app.snack_bar.show_snack_bar,
                                         record_name + " " + self._["record_stream_error"], 2000)
            except Exception as e:
                logger.debug(f"Failed to handle direct download error: {e}")
            return False
        finally:
            self.recording.record_url = None

    async def stop_recording_notify(self):
        if desktop_notify.should_push_notification(self.app):
            desktop_notify.send_notification(
                title=self._["notify"],
                message=self.recording.streamer_name + ' | ' + self._["live_recording_stopped_message"],
                app_icon=self.app.tray_manager.icon_path
            )

    async def end_message_push(self):
        msg_manager = message_pusher.MessagePusher(self.settings)
        user_config = self.settings.user_config

        if (self.app.recording_enabled and msg_manager.should_push_message(
                self.settings, self.recording, check_manually_stopped=True, message_type='end') and
                not self.recording.notified_live_end):
            self.recording.notified_live_end = True
            push_content = self._["push_content_end"]
            end_push_message_text = user_config.get("custom_stream_end_content")
            if end_push_message_text:
                push_content = end_push_message_text

            push_at = datetime.today().strftime("%Y-%m-%d %H:%M:%S")
            push_content = push_content.replace("[room_name]", self.recording.streamer_name).replace(
                "[time]", push_at
            )
            msg_title = user_config.get("custom_notification_title").strip()
            msg_title = msg_title or self._["status_notify"]

            self.app.page.run_task(msg_manager.push_messages, msg_title, push_content)

    async def _monitor_file_speed(self, save_file_path: str, process=None):
        """Monitor file writing speed by checking file size (unified method)"""
        try:
            last_size = 0
            last_time = time.time()
            
            while self.recording.is_recording:
                await asyncio.sleep(3)  # Check every 3 seconds (reduced frequency)
                
                # 如果是FFmpeg进程，检查进程是否还在运行
                if process and hasattr(process, 'returncode') and process.returncode is not None:
                    logger.debug("FFmpeg process ended, stopping speed monitoring")
                    break
                
                try:
                    if os.path.exists(save_file_path):
                        current_size = os.path.getsize(save_file_path)
                        current_time = time.time()
                        
                        if current_time > last_time:
                            bytes_diff = current_size - last_size
                            time_diff = current_time - last_time
                            
                            if time_diff > 0 and bytes_diff >= 0:
                                bytes_per_sec = bytes_diff / time_diff
                                if bytes_per_sec >= 1024 * 1024:  # MB/s
                                    self.recording.speed = f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"
                                elif bytes_per_sec >= 1024:  # KB/s
                                    self.recording.speed = f"{bytes_per_sec / 1024:.0f} KB/s"
                                else:  # B/s
                                    self.recording.speed = f"{bytes_per_sec:.0f} B/s"
                            else:
                                self.recording.speed = "0 B/s"
                            
                            # 只在速度变化时更新UI
                            old_speed = getattr(self, '_last_monitored_speed', '')
                            if old_speed != self.recording.speed:
                                self._last_monitored_speed = self.recording.speed
                                try:
                                    self.app.page.pubsub.send_others_on_topic("update", self.recording)
                                    logger.debug(f"Speed updated: {self.recording.speed}")
                                except Exception as e:
                                    logger.debug(f"Failed to update speed in UI: {e}")
                            
                            last_size = current_size
                            last_time = current_time
                        else:
                            logger.debug("No time difference for speed calculation")
                    else:
                        logger.debug(f"File not found: {save_file_path}")
                        
                except Exception as e:
                    logger.debug(f"Error checking file size: {e}")
                    
        except asyncio.CancelledError:
            logger.debug("File speed monitoring cancelled")
        except Exception as e:
            logger.error(f"Error in file speed monitoring: {e}")
