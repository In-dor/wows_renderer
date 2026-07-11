FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖 (OpenCV, Matplotlib 等需要)
# 添加重试和 --fix-missing 以应对代理/网络不稳定导致的 502 错误
RUN apt-get update && apt-get install -y \
    -o Acquire::Retries=3 \
    -o Acquire::http::Timeout=30 \
    -o Acquire::https::Timeout=30 \
    --fix-missing \
    git \
    ffmpeg \
    libsm6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# 安装服务端依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 minimap_renderer
ARG MINIMAP_RENDERER_COMMIT=03027639d1308e523ff0a61e9014d4c6bb352ba2
RUN pip install --no-cache-dir "git+https://github.com/In-dor/minimap_renderer.git@${MINIMAP_RENDERER_COMMIT}"

# 复制服务代码
COPY server.py .

RUN useradd --create-home --uid 10001 renderer
USER renderer

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
