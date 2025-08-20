#!/usr/bin/env python3
"""
测试404错误检测和文件写入功能
"""

import asyncio
import tempfile
import os
from app.core.media.direct_downloader import DirectStreamDownloader


async def test_404_detection():
    """测试404错误检测"""
    print("🧪 测试404错误检测...")
    
    # 使用一个肯定会返回404的URL
    test_url = "https://httpbin.org/status/404"
    
    with tempfile.NamedTemporaryFile(suffix='.test', delete=False) as tmp_file:
        save_path = tmp_file.name
    
    try:
        # 测试常规流的404检测
        print("\n📋 测试常规流404检测:")
        downloader = DirectStreamDownloader(
            record_url=test_url,
            save_path=save_path,
            max_retries=1,  # 减少重试次数以加快测试
            retry_delay=1
        )
        
        print(f"  URL: {test_url}")
        print(f"  是否自定义流: {downloader.is_custom_stream}")
        
        # 启动下载，应该很快因为404而停止
        await downloader.start_download()
        await asyncio.sleep(3)  # 等待3秒
        await downloader.stop_download()
        
        # 检查文件大小，应该是0或很小
        file_size = os.path.getsize(save_path) if os.path.exists(save_path) else 0
        print(f"  文件大小: {file_size} bytes")
        
        if file_size == 0:
            print("  ✅ 常规流404检测正常（文件大小为0）")
        else:
            print("  ❌ 常规流404检测可能有问题")
        
        # 测试自定义流的404检测
        print("\n📋 测试自定义流404检测:")
        custom_url = "https://httpbin.org/status/404.flv"  # 添加.flv后缀使其被识别为自定义流
        
        downloader2 = DirectStreamDownloader(
            record_url=custom_url,
            save_path=save_path + "_custom",
            custom_stream_buffer_time=10,  # 减少缓冲时间以加快测试
            custom_stream_retry_interval=2
        )
        
        print(f"  URL: {custom_url}")
        print(f"  是否自定义流: {downloader2.is_custom_stream}")
        
        # 启动下载，应该很快因为404而停止
        await downloader2.start_download()
        await asyncio.sleep(5)  # 等待5秒
        await downloader2.stop_download()
        
        # 检查文件大小
        custom_file_size = os.path.getsize(save_path + "_custom") if os.path.exists(save_path + "_custom") else 0
        print(f"  文件大小: {custom_file_size} bytes")
        
        if custom_file_size == 0:
            print("  ✅ 自定义流404检测正常（文件大小为0）")
        else:
            print("  ❌ 自定义流404检测可能有问题")
        
        return file_size == 0 and custom_file_size == 0
        
    except Exception as e:
        print(f"❌ 测试过程中出现异常: {e}")
        return False
    finally:
        # 清理临时文件
        for path in [save_path, save_path + "_custom"]:
            if os.path.exists(path):
                os.unlink(path)


async def test_successful_download():
    """测试成功下载的情况"""
    print("\n🧪 测试成功下载...")
    
    # 使用httpbin返回一些数据
    test_url = "https://httpbin.org/bytes/1024"  # 返回1KB数据
    
    with tempfile.NamedTemporaryFile(suffix='.test', delete=False) as tmp_file:
        save_path = tmp_file.name
    
    try:
        downloader = DirectStreamDownloader(
            record_url=test_url,
            save_path=save_path,
            max_retries=1,
            retry_delay=1
        )
        
        print(f"  URL: {test_url}")
        print(f"  是否自定义流: {downloader.is_custom_stream}")
        
        # 启动下载
        await downloader.start_download()
        
        # 等待下载完成或超时
        for i in range(10):  # 最多等待10秒
            await asyncio.sleep(1)
            if os.path.exists(save_path):
                file_size = os.path.getsize(save_path)
                if file_size > 0:
                    print(f"    第{i+1}秒: 文件大小 {file_size} bytes")
                    break
        
        await downloader.stop_download()
        
        # 检查文件大小
        file_size = os.path.getsize(save_path) if os.path.exists(save_path) else 0
        print(f"  文件大小: {file_size} bytes")
        
        if file_size > 0:
            print("  ✅ 成功下载测试通过")
            return True
        else:
            print("  ❌ 成功下载测试失败")
            return False
        
    except Exception as e:
        print(f"❌ 测试过程中出现异常: {e}")
        return False
    finally:
        # 清理临时文件
        if os.path.exists(save_path):
            os.unlink(save_path)


async def main():
    """主测试函数"""
    print("🚀 开始测试DirectStreamDownloader的404检测和下载功能...")
    
    tests = [
        ("404错误检测", test_404_detection),
        ("成功下载", test_successful_download),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n{'='*60}")
        print(f"测试: {test_name}")
        print('='*60)
        
        try:
            result = await test_func()
            if result:
                passed += 1
                print(f"✅ {test_name} 通过")
            else:
                print(f"❌ {test_name} 失败")
        except Exception as e:
            print(f"❌ {test_name} 异常: {e}")
    
    print(f"\n{'='*60}")
    print(f"测试总结: {passed}/{total} 通过")
    print('='*60)
    
    if passed == total:
        print("🎉 所有测试通过！404检测和下载功能正常")
    else:
        print("⚠️  部分测试失败，需要进一步检查")


if __name__ == "__main__":
    asyncio.run(main())