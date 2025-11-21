FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖 (OpenCV, Matplotlib 等需要)
RUN apt-get update && apt-get install -y \
    git \
    ffmpeg \
    libsm6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# 安装服务端依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 minimap_renderer
# 使用 --upgrade --force-reinstall 确保拉取最新版
RUN pip install --no-cache-dir --upgrade --force-reinstall git+https://github.com/WoWs-Builder-Team/minimap_renderer.git

# 复制服务代码
COPY server.py .

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
