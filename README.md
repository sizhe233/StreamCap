# StreamCap Fork - 定制版本 🚀

<div align="center">
  <img src="./assets/images/logo.svg" alt="StreamCap Fork" />
</div>

<p align="center">
  <img alt="Python version" src="https://img.shields.io/badge/python-3.10%2B-blue.svg">
  <img alt="Supported Platforms" src="https://img.shields.io/badge/Platforms-Win%20%7C%20Mac%20%7C%20Linux-6B5BFF.svg">
  <img alt="License" src="https://img.shields.io/badge/License-Apache%202.0-green.svg">
  <img alt="Fork" src="https://img.shields.io/badge/Fork-Enhanced-orange.svg">
</p>

<div align="center">
  <strong>基于 <a href="https://github.com/ihmily/StreamCap">ihmily/StreamCap</a> 的定制版本</strong><br>
  针对特定使用场景进行了功能扩展和优化
</div>

<br>

> **⚡ 主要优势**: 解决自定义FLV流限流问题 | 完整API接口支持 | 智能错误处理 | 实时速度监控

---

## 🎯 为什么选择这个Fork？

### 🔥 核心优化
- **避免限流问题**: 自定义FLV流智能检测，显著减少被平台限流的风险
- **API接口支持**: 完整的RESTful API，支持程序化控制录制
- **启动优化**: 程序启动时逐一间隔检测，避免同时请求导致限流
- **自动错误处理**: 智能识别404等错误，自动清理失败任务

### ⚡ 性能提升
- **实时速度监控**: 录制过程中显示实时下载速度
- **智能任务管理**: 自定义流录制完成后自动清理
- **优化日志系统**: 减少不必要的日志输出，提升性能
- **防死锁机制**: 改进UI更新逻辑，避免界面卡死

## 🚀 快速开始

### 方式一：下载预构建版本（推荐）
```bash
# 克隆增强版本
git clone https://github.com/sizhe233/StreamCap.git
cd StreamCap

# 安装依赖
pip install -r requirements.txt

# 启动程序（支持API接口）
python main.py --api-port 8000
```

### 方式二：API接口使用
```bash
# 开始录制（最简参数）
curl -X POST "http://127.0.0.1:8000/record/start" \
  -H "Content-Type: application/json" \
  -d '{"anchor_name": "主播名称", "stream_url": "http://example.com/stream.flv"}'

# 查询录制状态（支持模糊匹配）
curl -X GET "http://127.0.0.1:8000/record/status/主播%"

# 停止录制
curl -X POST "http://127.0.0.1:8000/record/stop" \
  -H "Content-Type: application/json" \
  -d '{"anchor_name": "主播名称"}'
```

## ✨ 扩展功能详解

### 1. FastAPI 接口支持 🔌
- **完整的RESTful API**: `/record/start`, `/record/stop`, `/record/status`
- **模糊查询支持**: 使用`%`通配符进行主播名称模糊匹配
- **CORS跨域支持**: 支持前端应用集成
- **详细API文档**: 访问 `http://127.0.0.1:8000/docs` 查看交互式文档

### 2. 自定义流检测优化 ⚡
- **智能检测策略**: 自定义流直接开始录制，跳过不必要的检测
- **平台分组检测**: 按平台分组，避免频繁请求同一平台
- **可配置间隔**: 新增`startup_check_interval`配置项
- **自动任务清理**: 录制完成后自动移除任务

### 3. 错误处理扩展 🛡️
- **智能错误识别**: 自动识别404、连接拒绝等关键错误
- **自动任务清理**: 失败任务自动移除，保留已下载文件
- **超时保护机制**: UI操作添加2-5秒超时保护
- **页面连接检测**: 避免在页面断开时执行UI操作

### 4. 性能监控 📊
- **实时速度显示**: 支持MB/s、KB/s、B/s多单位显示
- **文件系统优化**: 修复Windows文件名兼容性问题
- **日志系统优化**: 减少冗余日志，提升性能

## 📋 配置说明

### 新增配置项
```json
{
  "startup_check_interval": "3"  // 启动检测间隔（秒）
}
```

### 推荐配置（避免限流）
```json
{
  "loop_time_seconds": "300",
  "startup_check_interval": "3",
  "platform_max_concurrent_requests": "2"
}
```

### API服务配置
```bash
# 自定义API端口
python main.py --api-port 9000

# 同时配置Web和API端口
python main.py --port 8080 --api-port 9000
```

## 🎯 适用场景

### 推荐使用场景
- ✅ **经常遇到限流问题**的用户
- ✅ **需要API接口控制**录制的开发者
- ✅ **录制大量自定义FLV/M3U8流**的用户
- ✅ **对稳定性要求较高**的场景
- ✅ **需要批量管理录制任务**的用户

### 功能特色对比
| 功能         | 原版本       | 本Fork版本            |
| ------------ | ------------ | --------------------- |
| 自定义流检测 | 标准定时检测 | 针对限流场景优化 ✅    |
| API接口      | Web界面操作  | 额外提供RESTful API ✅ |
| 错误处理     | 标准错误处理 | 增加自动恢复机制 ✅    |
| 启动检测     | 标准检测方式 | 逐一间隔检测 ✅        |
| 速度监控     | 基础状态显示 | 实时速度显示 ✅        |

## 📚 文档链接

- 📖 **[完整功能文档](FORK_README.md)** - 详细的功能说明和技术细节
- 🔌 **[API使用文档](API_README.md)** - 完整的API接口说明
- 📜 **[原项目文档](ORIGINAL_README.md)** - 原始项目的完整文档
- 🔄 **[同步上游指南](sync_upstream.py)** - 如何同步上游更新

## 🔄 版本历史

### v1.2.0 (2025-08-09) - 当前版本
- ✅ 自定义FLV流检测机制优化，避免限流问题
- ✅ 程序启动时逐一间隔检测功能
- ✅ 录制速度实时监控
- ✅ 404错误自动处理机制
- ✅ UI更新和错误处理逻辑改进

### v1.1.0 (2025-08-07)
- ✅ 完整的FastAPI接口支持
- ✅ 模糊查询和CORS支持
- ✅ 多项UI更新和错误处理改进

## 🤝 贡献与支持

### 问题反馈
- 🐛 **Bug报告**: [提交Issue](https://github.com/sizhe233/StreamCap/issues)
- 💡 **功能建议**: 欢迎提出改进建议
- 📚 **文档改进**: 帮助完善使用文档

### 与上游关系
- **基于**: [ihmily/StreamCap](https://github.com/ihmily/StreamCap) 的 `fast_api` 分支
- **扩展内容**: 15+ 个功能扩展和优化
- **兼容性**: 完全兼容原版本
- **同步策略**: 定期同步上游更新，保持功能一致性

## 📄 许可证

本项目遵循 **Apache License 2.0** 开源许可证，与上游项目保持一致。

- **原项目**: [ihmily/StreamCap](https://github.com/ihmily/StreamCap) - Apache License 2.0
- **本Fork**: 所有修改和扩展功能同样采用 Apache License 2.0
- **使用权利**: 可自由使用、修改、分发，包括商业用途

详细许可证条款请参见 [LICENSE](LICENSE) 文件。

---

<div align="center">
  <strong>⭐ 如果这个项目对你有帮助，请给个Star支持一下！</strong><br><br>
  <strong>原项目</strong>: <a href="https://github.com/ihmily/StreamCap">ihmily/StreamCap</a><br>
  <strong>Fork维护者</strong>: <a href="https://github.com/sizhe233">sizhe233</a><br>
  <strong>最后更新</strong>: 2025-08-09
</div>