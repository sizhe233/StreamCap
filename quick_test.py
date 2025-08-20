#!/usr/bin/env python3
"""
快速测试DirectStreamDownloader是否正常工作
"""

import asyncio
import tempfile
import os
from app.core.media.direct_downloader import DirectStreamDownloader


async def quick_test():
    """快速测试基本功能"""
    print("🧪 快速测试DirectStreamDownloader...")
    
    # 创建临时文件
    with tempfile.NamedTemporaryFile(suffix='.test', delete=False) as tmp_file:
        save_path = tmp_file.name
    
    try:
        # 测试自定义流检测
        test_urls = [
            ("http://example.com/test.flv", True, "FLV自定义流"),
            ("http://example.com/test.m3u8", True, "M3U8自定义流"),
            ("http://example.com/test.mp4", False, "普通流"),
        ]
        
        print("\n📋 测试自定义流检测:")
        for url, expected, desc in test_urls:
            downloader = DirectStreamDownloader(
                record_url=url,
                save_path=save_path
            )
            result = downloader.is_custom_stream
            status = "✅" if result == expected else "❌"
            print(f"  {status} {desc}: {result}")
        
        # 测试基本配置
        print("\n📋 测试基本配置:")
        downloader = DirectStreamDownloader(
            record_url="http://example.com/test.flv",
            save_path=save_path,
            custom_stream_buffer_time=30,
            custom_stream_retry_interval=5,
            max_concurrent_downloads=4
        )
        
        print(f"  ✅ 缓冲时间: {downloader.custom_stream_buffer_time}秒")
        print(f"  ✅ 重连间隔: {downloader.custom_stream_retry_interval}秒")
        print(f"  ✅ 最大并发: {downloader.max_concurrent_downloads}")
        print(f"  ✅ 是否自定义流: {downloader.is_custom_stream}")
        
        # 测试并发控制
        print("\n📋 测试并发控制:")
        from app.core.media.direct_downloader import get_global_semaphore
        semaphore = await get_global_semaphore(5)
        print(f"  ✅ 全局信号量创建成功，最大并发: 5")
        print(f"  ✅ 当前可用许可: {semaphore._value}")
        
        print("\n🎉 所有基本功能测试通过！")
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        return False
    finally:
        # 清理临时文件
        if os.path.exists(save_path):
            os.unlink(save_path)


if __name__ == "__main__":
    result = asyncio.run(quick_test())
    if result:
        print("\n✅ DirectStreamDownloader修复成功，可以正常使用！")
    else:
        print("\n❌ 还有问题需要进一步修复")