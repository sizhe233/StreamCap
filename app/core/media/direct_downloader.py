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
                 speed_callback=None):
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
        try:
            os.makedirs(os.path.dirname(self.save_path), exist_ok=True)

            async with httpx.AsyncClient(headers=self.headers, proxy=self.proxy, timeout=None, follow_redirects=True) as client:
                async with client.stream("GET", self.record_url) as response:
                    if response.status_code not in [200, 206]:  # 200: OK, 206: Partial Content
                        if response.status_code == 404:
                            logger.error(f"直播流不存在或已结束, URL: {self.record_url}, Status Code: {response.status_code}")
                        elif response.status_code == 403:
                            logger.error(f"直播流访问被拒绝, URL: {self.record_url}, Status Code: {response.status_code}")
                        elif response.status_code >= 500:
                            logger.error(f"服务器错误, URL: {self.record_url}, Status Code: {response.status_code}")
                        else:
                            logger.error(f"请求流失败, URL: {self.record_url}, Status Code: {response.status_code}")
                        return

                    with open(self.save_path, 'wb') as f:
                        async for chunk in response.aiter_bytes(self.chunk_size):
                            if self.stop_event.is_set():
                                break

                            f.write(chunk)
                            self.total_bytes += len(chunk)

                            # Update speed every 2 seconds
                            current_time = time.time()
                            if current_time - self.last_speed_update >= 2.0:
                                elapsed = current_time - self.start_time
                                if self.speed_callback and elapsed > 0:
                                    self.speed_callback(self.total_bytes, elapsed)
                                self.last_speed_update = current_time

            if self.total_bytes > 0:
                logger.success(f"Download Completed: {self.save_path}")
            else:
                logger.warning(f"Download Failed - No data received: {self.save_path}")

        except asyncio.CancelledError:
            logger.info(f"Download Task Canceled: {self.record_url}")
        except Exception as e:
            logger.error(f"Download Error: {e}")
