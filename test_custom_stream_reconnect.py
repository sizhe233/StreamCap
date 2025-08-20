#!/usr/bin/env python3
"""
测试自定义流断流重连功能的脚本
"""

import asyncio
import time
from app.core.media.direct_downloader import DirectStreamDownloader


async def test_custom_stream_reconnect():
    """测试自定义流的断流重连功能"""
    
    # 模拟一个自定义流URL（FLV格式）
    test_url = "http://example.com/test_stream.flv"
    save_path = "./test_downloads/test_stream.flv"
    
    # 创建下载器实例，配置自定义流重连参数
    downloader = DirectStreamDownloader(
        record_url=test_url,
        save_path=save_path,
        custom_stream_buffer_time=30,  # 30秒缓冲时间（测试用）
        custom_stream_retry_interval=5,  # 5秒重连间隔（测试用）
        max_retries=3,
        retry_delay=2
    )
    
    print(f"测试URL: {test_url}")
    print(f"是否为自定义流: {downloader.is_custom_stream}")
    print(f"缓冲等待时间: {downloader.custom_stream_buffer_time}秒")
    print(f"重连间隔: {downloader.custom_stream_retry_interval}秒")
    
    # 由于这是一个无效的URL，会触发断流重连逻辑
    try:
        await downloader.start_download()
        
        # 等待一段时间观察重连行为
        await asyncio.sleep(40)  # 等待40秒，应该会看到重连尝试
        
    except Exception as e:
        print(f"测试过程中出现异常: {e}")
    finally:
        await downloader.stop_download()
        print("测试完成")


if __name__ == "__main__":
    print("开始测试自定义流断流重连功能...")
    asyncio.run(test_custom_stream_reconnect())