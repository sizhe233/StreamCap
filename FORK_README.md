# StreamCap Fork - 增强版本

这是 [ihmily/StreamCap](https://github.com/ihmily/StreamCap) 的fork版本，包含了大量功能增强和稳定性改进。

## 🚀 主要功能增强

### 1. FastAPI 接口支持
- **完整的 RESTful API 接口**：提供 `/record/start`、`/record/stop`、`/record/status` 等接口
- **模糊查询支持**：支持使用 `%` 通配符进行主播名称模糊匹配
- **CORS 跨域支持**：支持前端应用集成
- **详细的 API 文档**：包含 curl、PowerShell、Python 等多种调用示例
- **独立端口运行**：API 服务默认运行在 8000 端口，可通过 `--api-port` 参数自定义

#### API 使用示例
```bash
# 开始录制（最简参数）
curl -X POST "http://127.0.0.1:8000/record/start" \
  -H "Content-Type: application/json" \
  -d '{"anchor_name": "主播名称", "stream_url": "http://example.com/stream.flv"}'

# 模糊查询录制状态
curl -X GET "http://127.0.0.1:8000/record/status/主播%"  # 前缀匹配
curl -X GET "http://127.0.0.1:8000/record/status/%主播%"  # 包含匹配

# 停止录制
curl -X POST "http://127.0.0.1:8000/record/stop" \
  -H "Content-Type: application/json" \
  -d '{"anchor_name": "主播名称"}'
```

### 2. 自定义流检测机制优化 ⚡
- **智能检测策略**：自定义流任务直接开始录制，跳过不必要的定时检测
- **启动优化**：程序启动时逐一间隔检测现有任务，避免同时访问导致限流
- **平台分组检测**：按平台分组检测，避免对同一平台频繁请求
- **可配置间隔**：新增 `startup_check_interval` 配置项（默认3秒）
- **自动任务清理**：自定义流录制完成后自动从任务列表移除

### 3. 录制速度监控 📊
- **实时速度显示**：支持 FFmpeg 录制和直接下载器的实时速度监控
- **多单位显示**：自动切换 MB/s、KB/s、B/s 单位显示
- **UI 实时更新**：每2秒更新一次录制速度

### 4. 错误处理和稳定性改进 🛡️
- **智能错误检测**：自动识别 404、连接拒绝等关键错误
- **自动任务清理**：失败任务自动从列表移除，保留已下载文件
- **UI 更新优化**：修复 API 创建任务后前端页面不更新的问题
- **防死锁机制**：改进 `safe_remove_recording_sync` 方法，避免异步死锁
- **超时保护**：为 UI 操作添加超时保护机制（2-5秒）
- **页面连接检测**：智能检测页面连接状态，避免在页面断开时执行UI操作

### 5. 文件系统兼容性 📁
- **Windows 兼容性**：修复主播名字包含连续点号导致文件夹创建失败的问题
- **路径清理**：增强 `clean_name` 函数，确保文件路径符合系统规范
- **错误预防**：移除文件名中的非法字符，避免创建失败

### 6. 日志系统优化 📝
- **噪音减少**：减少频繁的 DEBUG 日志输出
- **状态感知**：只在录制状态变化时记录关键日志
- **错误聚焦**：保留重要的 INFO 和 WARNING 日志用于问题诊断
- **性能提升**：移除成功操作的冗余日志记录

### 7. 新增状态管理 🔄
- **新状态类型**：添加 `CUSTOM_STREAM_COMPLETED` 状态
- **生命周期管理**：优化录制任务的完整生命周期
- **多语言支持**：新状态的中英文翻译支持

## 📋 版本历史

### v1.2.0 (2025-08-09) - 最新版本
- ✅ **核心优化**：自定义FLV流检测机制优化，避免限流问题
- ✅ **启动改进**：程序启动时逐一间隔检测功能
- ✅ **速度监控**：添加录制速度实时监控
- ✅ **错误处理**：修复404错误自动处理机制
- ✅ **UI优化**：改进UI更新和错误处理逻辑
- ✅ **配置扩展**：新增 `startup_check_interval` 配置项
- ✅ **状态管理**：添加 `CUSTOM_STREAM_COMPLETED` 状态

### v1.1.0 (2025-08-07) - API版本
- ✅ **API接口**：完整的FastAPI接口支持
- ✅ **模糊查询**：支持通配符模糊查询
- ✅ **CORS支持**：跨域请求支持
- ✅ **文档完善**：详细的API使用文档
- ✅ **错误修复**：多项UI更新和错误处理改进

### v1.0.0 (2025-08-07) - 基础版本
- ✅ **基础功能**：基于上游 `fast_api` 分支
- ✅ **稳定性**：多项bug修复和稳定性改进

## 🛠️ 配置说明

### 新增配置项
```json
{
  "startup_check_interval": "3"  // 启动检测间隔（秒），默认3秒
}
```

### API 服务配置
```bash
# 自定义 API 端口启动
python main.py --api-port 9000

# 同时自定义 Web 端口和 API 端口
python main.py --port 8080 --api-port 9000
```

### 推荐配置
```json
{
  "loop_time_seconds": "300",           // 正常检测间隔5分钟
  "startup_check_interval": "3",        // 启动检测间隔3秒
  "platform_max_concurrent_requests": "2"  // 降低并发数避免限流
}
```

## 🔄 与上游仓库的关系

- **基础版本**：基于上游仓库的 `fast_api` 分支
- **改进数量**：包含 15+ 个功能改进和 bug 修复
- **兼容性**：保持与上游版本的完全兼容
- **同步策略**：定期同步上游更新，合并有用的新功能

### 分支说明
- `fast_api`: 主开发分支，包含所有改进功能
- `main`: 与上游保持同步的分支（如果需要）

## 🔄 同步上游更新

### 使用脚本同步（推荐）
```bash
# Windows用户
sync_upstream.bat

# Linux/Mac用户
python sync_upstream.py
```

### 手动同步步骤
```bash
# 1. 获取上游更新
git fetch upstream

# 2. 切换到主分支
git checkout fast_api

# 3. 合并上游更新
git merge upstream/fast_api

# 4. 解决冲突（如果有）
# 编辑冲突文件，然后：
git add .
git commit -m "merge: 同步上游更新"

# 5. 推送到自己的仓库
git push origin fast_api
```

## 🎯 适用场景

### 推荐使用场景
- **API 集成需求**：需要通过程序接口控制录制
- **批量管理**：需要管理大量录制任务
- **自定义流录制**：主要录制 FLV/M3U8 自定义流
- **稳定性要求高**：对程序稳定性有较高要求
- **避免限流**：经常遇到平台限流问题

### 性能优势
- **限流避免**：自定义流用户可显著减少被限流的风险
- **启动速度**：大量任务时启动检测更加平滑
- **资源占用**：优化的日志系统减少不必要的 I/O 操作
- **错误恢复**：自动处理常见错误，减少人工干预

## 🤝 贡献指南

### 问题反馈
- 🐛 **Bug 报告**：请提供详细的错误信息和复现步骤
- 💡 **功能建议**：欢迎提出新功能需求和改进建议
- 📚 **文档改进**：帮助完善使用文档和 API 说明

### 代码贡献
1. **Fork 本仓库**
2. **创建功能分支**：`git checkout -b feature/new-feature`
3. **提交更改**：`git commit -m "feat: 添加新功能"`
4. **推送分支**：`git push origin feature/new-feature`
5. **创建 Pull Request**

### 上游贡献
对于可能对上游有用的改进，我们也会考虑向上游提交，包括：
- 通用的错误处理改进
- 性能优化方案
- 用户体验改进

## 📚 相关文档

- [API 使用文档](API_README.md) - 详细的 API 接口说明
- [上游项目](https://github.com/ihmily/StreamCap) - 原始项目地址
- [同步脚本说明](sync_upstream.py) - 自动同步脚本

## 📄 许可证

本项目遵循 Apache License 2.0 开源许可证，与上游项目保持一致。

### 许可证声明
- **原项目**: [ihmily/StreamCap](https://github.com/ihmily/StreamCap) - Apache License 2.0
- **本Fork**: 所有修改和增强功能同样采用 Apache License 2.0
- **使用权利**: 可自由使用、修改、分发，包括商业用途
- **义务要求**: 需保留原始许可证声明和版权信息

详细许可证条款请参见 [LICENSE](LICENSE) 文件。

---

**原项目**: [ihmily/StreamCap](https://github.com/ihmily/StreamCap)  
**Fork维护者**: [sizhe233](https://github.com/sizhe233)  
**最后更新**: 2025-08-09