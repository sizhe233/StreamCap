import asyncio
import os
import time
from typing import Optional

import httpx

from ...utils.logger import logger


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
                 retry_delay: int = 5):
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
        """下载直播流，支持自动重连机制"""
        while self.current_retry <= self.max_retries and not self.stop_event.is_set():
            try:
                if self.current_retry > 0:
                    self.is_reconnecting = True
                    logger.info(f"尝试重连直播流 (第{self.current_retry}/{self.max_retries}次): {self.record_url}")
                    await asyncio.sleep(self.retry_delay)
                
                os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
                
                # 如果是重连，以追加模式打开文件
                file_mode = 'ab' if self.current_retry > 0 and self.total_bytes > 0 else 'wb'
                
                async with httpx.AsyncClient(headers=self.headers, proxy=self.proxy, timeout=30.0, follow_redirects=True) as client:
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
