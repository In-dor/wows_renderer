# WoWs Minimap Renderer Plugin

战舰世界小地图回放渲染插件，用于 NoneBot2 机器人。
本插件可以接收群聊中的 `.wowsreplay` 回放文件，并调用 `minimap_renderer` 引擎将其渲染为小地图战局视频。

## 功能特点

- 自动识别群聊中的 `.wowsreplay` 文件
- 生成战局小地图视频
- 支持**本地渲染**（默认）和**远程 Docker 渲染**（推荐）两种模式
- Docker 部署友好，支持独立更新渲染器

## 安装与配置

### 1. 基础配置

在 NoneBot2 项目的 `.env` 文件中添加以下配置：

```dotenv
# 渲染器项目路径（必须，作为工作目录）
RENDERER_PROJECT_PATH="/path/to/minimap_renderer"

# 渲染超时时间（秒，默认 600）
RENDER_TIMEOUT=600
```

### 2. 部署模式选择

本插件支持两种部署模式，请根据需求选择其中一种。

#### 模式 A：独立 Docker 服务（推荐）

此模式将渲染器作为一个独立的 HTTP 服务运行，与 Bot 解耦。适合 Docker 部署，渲染器更新无需重启 Bot。

**服务端部署：**

1.  进入插件目录下的 `wows_renderer/docker` 文件夹。
2.  运行 `docker-compose up -d` 启动渲染服务（默认端口 8000）。

**插件配置：**

在 `.env` 中添加：

```dotenv
# 远程渲染 API 地址
RENDERER_API_ENDPOINT="http://localhost:8000"
# 如果 Bot 也在 Docker 中，请使用容器名或宿主机 IP
# RENDERER_API_ENDPOINT="http://wows-renderer-service:8000"
```

---

#### 模式 B：本地渲染

此模式直接调用本地 Python 环境中的 `minimap_renderer`。

**环境准备：**

确保本地已安装 `minimap_renderer`：

```bash
pip install --upgrade --force-reinstall git+https://github.com/WoWs-Builder-Team/minimap_renderer.git
```

**插件配置：**

在 `.env` 中添加：

```dotenv
# 指定 Python 解释器路径（如果不指定，默认尝试在项目目录下寻找 venv）
RENDERER_PYTHON_PATH="/path/to/venv/bin/python"
# Windows 示例:
# RENDERER_PYTHON_PATH="C:\\Users\\Admin\\venv\\Scripts\\python.exe"
```

## 使用方法

1.  将机器人拉入群聊。
2.  发送 `.wowsreplay` 结尾的战舰世界回放文件。
3.  机器人会自动下载并开始渲染，完成后发送视频。

## 常见问题

**Q: 渲染器更新了怎么办？**

- **Docker 模式**：进入 `wows_renderer/docker` 目录，运行 `docker-compose build --no-cache` 重新构建镜像，然后重启服务即可。Bot 无需重启。
- **本地模式**：在指定的 Python 环境中重新运行 `pip install` 命令更新包。

**Q: 渲染速度很慢？**

- 渲染过程涉及大量的图像处理和视频编码，通常需要消耗较多 CPU 资源。
- 如果使用 Docker 模式，可以在 `docker-compose.yml` 中限制资源或将其部署在性能更强的机器上。
