import asyncio
import os
import time
from typing import Optional

import httpx

from ...utils.logger import logger


# 全局并发控制信号量
_global_semaphore = None

async def get_global_semaphore(max_concurrent: int = 8) -> asyncio.Semaphore:
    """获取全局并发控制信号量"""
    global _global_semaphore
    if _global_semaphore is None:
        _global_semaphore = asyncio.Semaphore(max_concurrent)
    return _global_semaphore


class DirectStreamDownloader:
    """
    Directly download the live stream using HTTP requests, used to handle FLV streams that ffmpeg cannot handle normally
    """

    def __init__(self,
                 record_url: str,
                 save_path: str,
                 headers: Optional[dict[str, str]] = None,
                 proxy: Optional[str] = None,
                 chunk_size: int = 1024 * 16,  # 16KB chunks
                 speed_callback=None,
                 max_retries: int = 3,
                 retry_delay: int = 5,
                 custom_stream_buffer_time: int = 60,  # 自定义流缓冲等待时间（秒）
                 custom_stream_retry_interval: int = 10,  # 自定义流重连间隔（秒）
                 max_concurrent_downloads: int = 10):  # 最大并发下载数
        self.record_url = record_url
        self.save_path = save_path
        self.headers = headers or {}
        self.proxy = proxy or None
        self.chunk_size = chunk_size
        self.stop_event = asyncio.Event()
        self.process = None
        self.download_task = None
        self.total_bytes = 0
        self.start_time = None
        self.speed_callback = speed_callback
        self.last_speed_update = 0
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.current_retry = 0
        self.is_reconnecting = False
        
        # 自定义流断流重连策略参数
        self.custom_stream_buffer_time = custom_stream_buffer_time
        self.custom_stream_retry_interval = custom_stream_retry_interval
        self.disconnect_start_time = None
        self.is_custom_stream = self._is_custom_stream_url(record_url)
        self.max_concurrent_downloads = max_concurrent_downloads
        
        # 自定义流专用的重连计数器，与原有机制分离
        self.custom_retry_count = 0
        
        # 连接稳定性监控
        self.connection_failures = 0
        self.last_successful_connection = None
        self.adaptive_retry_delay = custom_stream_retry_interval

    async def start_download(self) -> bool:
        self.start_time = time.time()
        self.download_task = asyncio.create_task(self._download_stream())
        return True

    async def stop_download(self) -> None:
        if not self.stop_event.is_set():
            self.stop_event.set()
            if self.download_task:
                try:
                    await asyncio.wait_for(self.download_task, timeout=10.0)
                except asyncio.TimeoutError:
                    logger.warning(f"Download Timeout: {self.record_url}")
                except Exception as e:
                    logger.error(f"Download Error: {e}")

    async def _download_stream(self) -> None:
        """下载直播流，支持自动重连机制和自定义流断流策略"""
        if self.is_custom_stream:
            await self._download_custom_stream()
        else:
            await self._download_regular_stream()

    async def _download_regular_stream(self) -> None:
        """常规直播流下载逻辑（原有逻辑）"""
        while self.current_retry <= self.max_retries and not self.stop_event.is_set():
            try:
                if self.current_retry > 0:
                    self.is_reconnecting = True
                    logger.info(f"尝试重连直播流 (第{self.current_retry}/{self.max_retries}次): {self.record_url}")
                    await asyncio.sleep(self.retry_delay)
                
                os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
                
                # 如果是重连，以追加模式打开文件
                file_mode = 'ab' if self.current_retry > 0 and self.total_bytes > 0 else 'wb'
                
                # 为了避免复杂的代理配置问题，暂时回到独立客户端
                # TODO: 后续优化为共享客户端池
                timeout = httpx.Timeout(
                    connect=10.0,    # 连接超时
                    read=30.0,       # 读取超时
                    write=10.0,      # 写入超时
                    pool=5.0         # 连接池超时
                )
                
                async with httpx.AsyncClient(
                    headers=self.headers, 
                    proxy=self.proxy, 
                    timeout=timeout, 
                    follow_redirects=True
                ) as client:
                    async with client.stream("GET", self.record_url) as response:
                        if response.status_code not in [200, 206]:  # 200: OK, 206: Partial Content
                            # 检查是否为关键错误（不应重试）
                            if response.status_code in [404, 403, 410]:  # 404: Not Found, 403: Forbidden, 410: Gone
                                if response.status_code == 404:
                                    logger.error(f"直播流不存在或已结束, URL: {self.record_url}, Status Code: {response.status_code}")
                                elif response.status_code == 403:
                                    logger.error(f"直播流访问被拒绝, URL: {self.record_url}, Status Code: {response.status_code}")
                                elif response.status_code == 410:
                                    logger.error(f"直播流已不可用, URL: {self.record_url}, Status Code: {response.status_code}")
                                return  # 关键错误，不重试
                            else:
                                # 非关键错误，可以重试
                                logger.warning(f"请求流失败 (可重试), URL: {self.record_url}, Status Code: {response.status_code}")
                                raise Exception(f"HTTP {response.status_code}")

                        with open(self.save_path, file_mode) as f:
                            self.is_reconnecting = False
                            if self.current_retry > 0:
                                logger.info(f"重连成功，继续下载: {self.record_url}")
                            
                            async for chunk in response.aiter_bytes(self.chunk_size):
                                if self.stop_event.is_set():
                                    logger.info(f"收到停止信号，结束下载: {self.record_url}")
                                    return

                                f.write(chunk)
                                self.total_bytes += len(chunk)

                                # Update speed every 2 seconds
                                current_time = time.time()
                                if current_time - self.last_speed_update >= 2.0:
                                    elapsed = current_time - self.start_time
                                    if self.speed_callback and elapsed > 0:
                                        self.speed_callback(self.total_bytes, elapsed)
                                    self.last_speed_update = current_time

                # 如果到达这里，说明连接正常结束（可能是流结束）
                if self.total_bytes > 0:
                    logger.success(f"Download Completed: {self.save_path}")
                else:
                    logger.warning(f"Download Failed - No data received: {self.save_path}")
                return

            except asyncio.CancelledError:
                logger.info(f"Download Task Canceled: {self.record_url}")
                return
            except Exception as e:
                self.current_retry += 1
                error_msg = str(e).lower()
                
                # 检查是否为不应重试的关键错误
                critical_errors = ['404', 'not found', 'forbidden', 'unauthorized', 'gone']
                if any(error in error_msg for error in critical_errors):
                    logger.error(f"关键错误，停止重试: {e}")
                    return
                
                if self.current_retry <= self.max_retries:
                    logger.warning(f"下载出错，将在{self.retry_delay}秒后重试 (第{self.current_retry}/{self.max_retries}次): {e}")
                else:
                    logger.error(f"达到最大重试次数，下载失败: {e}")
                    return

    def _is_custom_stream_url(self, url: str) -> bool:
        """判断是否为自定义流URL（FLV或M3U8）"""
        return '.flv' in url.lower() or '.m3u8' in url.lower()
    async def _download_custom_stream(self) -> None:
        """自定义流下载逻辑，支持断流缓冲等待和重连策略"""
        logger.info(f"开始下载自定义流，启用断流重连策略: {self.record_url}")
        
        while not self.stop_event.is_set():
            try:
                # 如果是重连尝试，显示重连信息
                if self.custom_retry_count > 0:
                    self.is_reconnecting = True
                    logger.info(f"自定义流重连尝试 (第{self.custom_retry_count}次): {self.record_url}")
                
                os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
                
                # 如果是重连，以追加模式打开文件
                file_mode = 'ab' if self.custom_retry_count > 0 and self.total_bytes > 0 else 'wb'
                
                # 使用并发控制信号量，避免同时创建过多连接
                semaphore = await get_global_semaphore(self.max_concurrent_downloads)
                
                # 创建等待状态更新任务
                waiting_update_task = None
                
                # 检查是否需要等待并发槽位
                if semaphore._value == 0:  # 信号量值为0表示已满
                    logger.info(f"并发槽位已满，等待空闲槽位: {self.record_url}")
                    
                    # 创建等待期间的UI更新任务
                    async def waiting_status_update():
                        while semaphore._value == 0 and not self.stop_event.is_set():
                            if self.speed_callback:
                                current_time = time.time()
                                elapsed = current_time - self.start_time
                                self.speed_callback(0, elapsed)  # 显示等待状态
                            await asyncio.sleep(2)  # 每2秒更新一次
                    
                    waiting_update_task = asyncio.create_task(waiting_status_update())
                
                try:
                    async with semaphore:
                        # 取消等待状态更新任务
                        if waiting_update_task:
                            waiting_update_task.cancel()
                            try:
                                await waiting_update_task
                            except asyncio.CancelledError:
                                pass
                        
                        logger.info(f"获得并发槽位，开始下载: {self.record_url}")
                        
                        # 为了避免复杂的代理配置问题，使用独立客户端
                        timeout = httpx.Timeout(
                            connect=10.0,    # 连接超时
                            read=30.0,       # 读取超时
                            write=10.0,      # 写入超时
                            pool=5.0         # 连接池超时
                        )
                        
                        async with httpx.AsyncClient(
                            headers=self.headers, 
                            proxy=self.proxy, 
                            timeout=timeout, 
                            follow_redirects=True
                        ) as client:
                            async with client.stream("GET", self.record_url) as response:
                                if response.status_code not in [200, 206]:  # 200: OK, 206: Partial Content
                                    # 检查是否为关键错误（不应重试）
                                    if response.status_code in [404, 403, 410]:  # 404: Not Found, 403: Forbidden, 410: Gone
                                        if response.status_code == 404:
                                            logger.error(f"自定义流不存在或已结束, URL: {self.record_url}, Status Code: {response.status_code}")
                                        elif response.status_code == 403:
                                            logger.error(f"自定义流访问被拒绝, URL: {self.record_url}, Status Code: {response.status_code}")
                                        elif response.status_code == 410:
                                            logger.error(f"自定义流已不可用, URL: {self.record_url}, Status Code: {response.status_code}")
                                        return  # 关键错误，不重试
                                    else:
                                        # 非关键错误，触发自定义流重连策略
                                        logger.warning(f"自定义流请求失败 (Status Code: {response.status_code})，启动断流重连策略")
                                        should_continue = await self._handle_custom_stream_disconnect(f"HTTP {response.status_code}")
                                        if not should_continue:
                                            return
                                        self.custom_retry_count += 1  # 增加重连计数
                                        continue

                                with open(self.save_path, file_mode) as f:
                                    # 重连成功，重置状态
                                    if self.is_reconnecting:
                                        self.is_reconnecting = False
                                        self.disconnect_start_time = None
                                        self.custom_retry_count = 0  # 重置自定义流重连计数器
                                        self.connection_failures = 0  # 重置连接失败计数
                                        self.last_successful_connection = time.time()
                                        self.adaptive_retry_delay = self.custom_stream_retry_interval  # 重置自适应延迟
                                        logger.info(f"自定义流重连成功，继续录制: {self.record_url}")
                                    else:
                                        # 首次连接成功
                                        self.last_successful_connection = time.time()
                                    
                                    async for chunk in response.aiter_bytes(self.chunk_size):
                                        if self.stop_event.is_set():
                                            logger.info(f"收到停止信号，结束自定义流下载: {self.record_url}")
                                            return

                                        f.write(chunk)
                                        self.total_bytes += len(chunk)

                                        # Update speed every 2 seconds
                                        current_time = time.time()
                                        if current_time - self.last_speed_update >= 2.0:
                                            elapsed = current_time - self.start_time
                                            if self.speed_callback and elapsed > 0:
                                                self.speed_callback(self.total_bytes, elapsed)
                                            self.last_speed_update = current_time

                    # 如果到达这里，说明连接正常结束（可能是流结束）
                    logger.info(f"自定义流连接结束，启动断流重连策略: {self.record_url}")
                    should_continue = await self._handle_custom_stream_disconnect("连接正常结束")
                    if not should_continue:
                        if self.total_bytes > 0:
                            logger.success(f"自定义流下载完成: {self.save_path}")
                        else:
                            logger.warning(f"自定义流下载失败 - 未接收到数据: {self.save_path}")
                        return
                    self.custom_retry_count += 1  # 增加重连计数
                except Exception:
                    # 如果出现异常，也要确保清理等待任务
                    if waiting_update_task and not waiting_update_task.done():
                        waiting_update_task.cancel()
                        try:
                            await waiting_update_task
                        except asyncio.CancelledError:
                            pass
                    raise

            except asyncio.CancelledError:
                logger.info(f"自定义流下载任务被取消: {self.record_url}")
                return
            except Exception as e:
                error_msg = str(e).lower()
                
                # 检查是否为关键错误
                critical_errors = ['404', 'not found', 'forbidden', 'unauthorized', 'gone']
                if any(error in error_msg for error in critical_errors):
                    logger.error(f"自定义流关键错误，停止重试: {e}")
                    return
                
                # 非关键错误，启动断流重连策略
                logger.warning(f"自定义流下载出错，启动断流重连策略: {e}")
                should_continue = await self._handle_custom_stream_disconnect(str(e))
                if not should_continue:
                    return
                self.custom_retry_count += 1  # 增加重连计数

    async def _handle_custom_stream_disconnect(self, error_reason: str) -> bool:
        """
        处理自定义流断流，实现缓冲等待和重连策略
        
        Returns:
            bool: True表示应该继续重连，False表示应该停止
        """
        current_time = time.time()
        
        # 增加连接失败计数
        self.connection_failures += 1
        
        # 如果是第一次断流，记录开始时间
        if self.disconnect_start_time is None:
            self.disconnect_start_time = current_time
            logger.info(f"自定义流断流检测，开始{self.custom_stream_buffer_time}秒缓冲等待期: {error_reason}")
        
        # 检查是否超过缓冲等待时间
        elapsed_time = current_time - self.disconnect_start_time
        if elapsed_time >= self.custom_stream_buffer_time:
            logger.warning(f"自定义流断流超过{self.custom_stream_buffer_time}秒，停止录制任务")
            return False  # 超时，停止重连
        
        # 自适应重连延迟：根据连接失败次数动态调整
        if self.connection_failures > 3:
            # 连接频繁失败，增加延迟
            self.adaptive_retry_delay = min(self.custom_stream_retry_interval * 2, 30)
            logger.info(f"检测到频繁断流，增加重连延迟至{self.adaptive_retry_delay}秒")
        elif self.connection_failures > 10:
            # 连接严重不稳定，进一步增加延迟
            self.adaptive_retry_delay = min(self.custom_stream_retry_interval * 3, 60)
            logger.info(f"连接严重不稳定，增加重连延迟至{self.adaptive_retry_delay}秒")
        
        # 在缓冲等待期内，每隔指定间隔进行重连尝试
        remaining_time = self.custom_stream_buffer_time - elapsed_time
        logger.info(f"自定义流断流重连，剩余等待时间: {remaining_time:.1f}秒，{self.adaptive_retry_delay}秒后重试 (失败次数: {self.connection_failures})")
        
        # 设置重连状态
        self.is_reconnecting = True
        
        # 使用自适应延迟
        await asyncio.sleep(self.adaptive_retry_delay)
        return True  # 继续重连