#!/usr/bin/env python3
"""
测试DirectStreamDownloader修复后的功能
"""

import asyncio
import os
import tempfile
from app.core.media.direct_downloader import DirectStreamDownloader


async def test_basic_download():
    """测试基本下载功能"""
    print("🧪 测试基本下载功能...")
    
    # 使用一个简单的测试URL（这里用httpbin作为测试）
    test_url = "https://httpbin.org/bytes/1024"  # 下载1KB数据
    
    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as tmp_file:
        save_path = tmp_file.name
    
    try:
        downloader = DirectStreamDownloader(
            record_url=test_url,
            save_path=save_path,
            max_concurrent_downloads=4
        )
        
        print(f"测试URL: {test_url}")
        print(f"保存路径: {save_path}")
        print(f"是否为自定义流: {downloader.is_custom_stream}")
        
        # 启动下载
        await downloader.start_download()
        
        # 等待一段时间
        await asyncio.sleep(5)
        
        # 停止下载
        await downloader.stop_download()
        
        # 检查文件大小
        if os.path.exists(save_path):
            file_size = os.path.getsize(save_path)
            print(f"✅ 下载完成，文件大小: {file_size} bytes")
            if file_size > 0:
                print("✅ 基本下载功能正常")
                return True
            else:
                print("❌ 文件大小为0，下载失败")
                return False
        else:
            print("❌ 文件不存在，下载失败")
            return False
            
    except Exception as e:
        print(f"❌ 测试过程中出现异常: {e}")
        return False
    finally:
        # 清理临时文件
        if os.path.exists(save_path):
            os.unlink(save_path)


async def test_custom_stream_detection():
    """测试自定义流检测功能"""
    print("\n🧪 测试自定义流检测功能...")
    
    test_cases = [
        ("http://example.com/stream.flv", True),
        ("http://example.com/stream.m3u8", True),
        ("http://example.com/stream.FLV", True),
        ("http://example.com/stream.M3U8", True),
        ("http://example.com/stream.mp4", False),
        ("http://example.com/stream", False),
    ]
    
    all_passed = True
    for url, expected in test_cases:
        downloader = DirectStreamDownloader(
            record_url=url,
            save_path="/tmp/test.bin"
        )
        result = downloader.is_custom_stream
        status = "✅" if result == expected else "❌"
        print(f"{status} {url} -> {result} (期望: {expected})")
        if result != expected:
            all_passed = False
    
    if all_passed:
        print("✅ 自定义流检测功能正常")
    else:
        print("❌ 自定义流检测功能有问题")
    
    return all_passed


async def test_concurrent_downloads():
    """测试并发下载控制"""
    print("\n🧪 测试并发下载控制...")
    
    # 创建多个下载任务
    tasks = []
    temp_files = []
    
    try:
        for i in range(5):
            tmp_file = tempfile.NamedTemporaryFile(suffix=f'_test_{i}.bin', delete=False)
            temp_files.append(tmp_file.name)
            tmp_file.close()
            
            downloader = DirectStreamDownloader(
                record_url=f"https://httpbin.org/bytes/512",  # 每个下载512字节
                save_path=temp_files[i],
                max_concurrent_downloads=2  # 限制并发数为2
            )
            
            task = asyncio.create_task(downloader.start_download())
            tasks.append((task, downloader))
        
        print(f"启动了 {len(tasks)} 个并发下载任务")
        
        # 等待一段时间
        await asyncio.sleep(8)
        
        # 停止所有下载
        for task, downloader in tasks:
            await downloader.stop_download()
        
        # 检查结果
        successful_downloads = 0
        for i, temp_file in enumerate(temp_files):
            if os.path.exists(temp_file):
                file_size = os.path.getsize(temp_file)
                if file_size > 0:
                    successful_downloads += 1
                    print(f"✅ 任务 {i+1}: {file_size} bytes")
                else:
                    print(f"❌ 任务 {i+1}: 0 bytes")
            else:
                print(f"❌ 任务 {i+1}: 文件不存在")
        
        if successful_downloads >= 3:  # 至少3个成功
            print(f"✅ 并发下载测试通过 ({successful_downloads}/{len(tasks)} 成功)")
            return True
        else:
            print(f"❌ 并发下载测试失败 ({successful_downloads}/{len(tasks)} 成功)")
            return False
            
    except Exception as e:
        print(f"❌ 并发测试过程中出现异常: {e}")
        return False
    finally:
        # 清理临时文件
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                os.unlink(temp_file)


async def main():
    """主测试函数"""
    print("🚀 开始测试DirectStreamDownloader修复...")
    
    tests = [
        ("基本下载功能", test_basic_download),
        ("自定义流检测", test_custom_stream_detection),
        ("并发下载控制", test_concurrent_downloads),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n{'='*50}")
        print(f"测试: {test_name}")
        print('='*50)
        
        try:
            result = await test_func()
            if result:
                passed += 1
                print(f"✅ {test_name} 通过")
            else:
                print(f"❌ {test_name} 失败")
        except Exception as e:
            print(f"❌ {test_name} 异常: {e}")
    
    print(f"\n{'='*50}")
    print(f"测试总结: {passed}/{total} 通过")
    print('='*50)
    
    if passed == total:
        print("🎉 所有测试通过！DirectStreamDownloader修复成功")
    else:
        print("⚠️  部分测试失败，需要进一步检查")


if __name__ == "__main__":
    asyncio.run(main())