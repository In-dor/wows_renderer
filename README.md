<div align="center">

# NoneBot Plugin WoWs Minimap Renderer

_✨ 战舰世界小地图回放渲染插件 ✨_

<p align="center">
  <a href="https://github.com/nonebot/nonebot2">
    <img src="https://img.shields.io/badge/nonebot-v2-red.svg" alt="nonebot">
  </a>
  <a href="https://python.org">
    <img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="python">
  </a>
</p>

</div>

本插件用于接收群聊中的 `.wowsreplay` 回放文件，并调用 `minimap_renderer` 引擎将其渲染为战局小地图动态视频。支持 **Docker 远程渲染** 和 **本地直接渲染** 两种模式。

## 📖 功能特点

- **自动识别**: 监听群聊消息，自动捕获 `.wowsreplay` 后缀文件。
- **双模式部署**:
  - 🐳 **Docker 模式 (推荐)**: 渲染服务独立运行，环境隔离，不阻塞 Bot 进程，更新方便。
  - 💻 **本地模式**: 直接调用本地 Python 环境，适合简单部署或调试。
- **自动清理**: 渲染完成后自动清理临时文件，节省磁盘空间。
- **灵活配置**: 支持自定义超时时间、文件路径及渲染参数。

## 💿 安装

### 1. 放置插件文件

本插件暂未发布到 PyPI，请使用以下方式手动安装：

1.  下载本仓库的 `wows_renderer` 文件夹。
2.  将其放入你的 NoneBot 项目的 `src/plugins` 目录中（或者任何你配置的插件目录）。

结构示例：

```text
你的Bot项目/
├── .env
├── bot.py
├── src/
│   └── plugins/
│       └── wows_renderer/  <-- 放置在这里
│           ├── __init__.py
│           ├── config.py
│           └── ...
```

### 2. 加载插件

先在 NoneBot 环境中安装插件依赖：

```bash
pip install -r requirements.txt
```

只要将插件文件夹放入了 NoneBot 能够自动加载的目录（通常是 `src/plugins`），插件就会自动加载，无需手动修改 `bot.py`。

> 注意：如果你的 Bot 配置了其他插件目录，请确保 `wows_renderer` 放在正确的位置。

## ⚙️ 配置指南

在 NoneBot2 项目的 `.env` 文件中添加以下配置。根据你选择的部署模式，配置会有所不同。

### 全局配置 (通用)

| 配置项                    | 类型 | 默认值                   | 说明                                           |
| :------------------------ | :--- | :----------------------- | :--------------------------------------------- |
| `RENDER_TIMEOUT`          | int  | 600                      | 渲染超时时间(秒)，建议设大一点以防长局渲染失败 |
| `WOWS_RENDER_TEMP_PATH`   | Path | cache/wows_render/temp   | 下载回放文件的临时目录                         |
| `WOWS_RENDER_OUTPUT_PATH` | Path | cache/wows_render/output | 输出视频的存储目录                             |
| `MAX_CONCURRENT_RENDERS`  | int  | 0                        | Bot 端最大并发渲染数，0 表示不限制              |
| `MAX_REPLAY_SIZE_MB`      | int  | 100                      | 最大回放文件大小                               |
| `MAX_VIDEO_SIZE_MB`       | int  | 300                      | 最大渲染结果及发送视频大小                     |
| `ENABLE_CLEANUP`          | bool | true                     | 是否在处理结束后清理临时文件                   |

---

### 🐳 部署模式 A：Docker 服务 (推荐)

此模式下，渲染器作为一个独立的 HTTP 服务运行。Bot 通过 API 调用渲染服务。

**1. 启动渲染服务**

在插件目录的 `docker/` 下提供了 `docker-compose.yml`。
你可以将 `docker` 目录复制到服务器任意位置，然后运行：

```bash
cd docker
docker-compose up -d
```

服务默认仅监听宿主机 `127.0.0.1:8089`，不会直接暴露到公网。跨主机部署时应通过带 TLS、请求体限制和限流的反向代理访问。

建议在 `docker/.env` 中设置访问令牌：

```dotenv
RENDERER_API_TOKEN="请替换为足够长的随机字符串"
```

**2. 插件配置 (.env)**

```dotenv
# 远程渲染 API 地址
# 注意：如果 Bot 也在 Docker 中，请使用宿主机 IP 或容器名 (如 http://wows-renderer-service:8000)
RENDERER_API_ENDPOINT="http://127.0.0.1:8089"
# 必须与 Docker 服务的 RENDERER_API_TOKEN 一致；服务未设置令牌时可省略
RENDERER_API_TOKEN="请替换为足够长的随机字符串"
```

---

### 💻 部署模式 B：本地渲染

此模式下，Bot 直接调用本地安装的 `minimap_renderer`。需要确保本地环境已安装 FFmpeg 和相关依赖。

**1. 环境准备**

确保系统已安装 `ffmpeg`。然后安装渲染器核心库：

```bash
# 确保 pip 升级到最新
pip install --upgrade pip
# 安装渲染器
pip install --upgrade --force-reinstall git+https://github.com/WoWs-Builder-Team/minimap_renderer.git
```

**2. 插件配置 (.env)**

```dotenv
# 渲染器项目路径 (通常设为 nonebot 运行目录或任意存在的目录即可，用作工作目录)
RENDERER_PROJECT_PATH="/path/to/your/bot/run/dir"

# (可选) 指定 Python 解释器路径
# 如果不指定，默认会尝试在 RENDERER_PROJECT_PATH/venv 下寻找，否则使用当前 Python 解释器
# RENDERER_PYTHON_PATH="/path/to/venv/bin/python"
```

## 🚀 使用方法

1.  将机器人拉入群聊。
2.  发送 `.wowsreplay` 结尾的战舰世界回放文件。
3.  机器人回复 "收到回放文件..." 并开始下载。
4.  渲染完成后，机器人会发送生成的 MP4 视频。

## ❓ 常见问题 (FAQ)

**Q: Docker 模式下 Bot 提示 "Connection refused"?**
A: 请检查 `.env` 中的 `RENDERER_API_ENDPOINT`。

- 如果 Bot 在宿主机运行，渲染器在 Docker，使用 `http://localhost:8089`。
- 如果 Bot 也在 Docker 容器中，不能用 localhost，请使用 `http://宿主机IP:8089` 或者确保它们在同一个 Docker Network 下使用容器名通信。

**Q: 渲染失败，日志显示 "No such file or directory: 'ffmpeg'"?**
A: 本地模式需要手动安装 FFmpeg 并添加到系统环境变量 PATH 中。Docker 模式镜像内已预装 FFmpeg。

**Q: 渲染速度很慢？**
A: 渲染过程是计算密集型的。

- Docker 模式：检查宿主机 CPU 负载，可以在 `docker-compose.yml` 中调整资源限制。
- 确保分配了足够的内存，处理长录像可能需要较多内存。

**Q: 如何更新渲染器？**

- **Docker 模式**:
  ```bash
  cd docker
  # 将提交号替换为经过验证的 minimap_renderer 版本
  docker-compose build --build-arg MINIMAP_RENDERER_COMMIT=<commit>
  docker-compose up -d
  ```
- **本地模式**:
  ```bash
  pip install --upgrade --force-reinstall git+https://github.com/WoWs-Builder-Team/minimap_renderer.git
  ```

## 📝 许可证

MIT
