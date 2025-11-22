import os
import time
import uuid
import shutil
import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse


# 配置日志
class ColoredFormatter(logging.Formatter):
    """自定义带有颜色的日志格式"""

    grey = "\x1b[38;20m"
    green = "\x1b[32;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    # 时间精确到秒
    datefmt = "%Y-%m-%d %H:%M:%S"
    fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    COLORS = {
        logging.DEBUG: grey,
        logging.INFO: green,
        logging.WARNING: yellow,
        logging.ERROR: red,
        logging.CRITICAL: bold_red,
    }

    def format(self, record):
        # 手动格式化时间，确保精确到秒且不包含毫秒
        date_format = self.datefmt if self.datefmt else "%Y-%m-%d %H:%M:%S"
        current_time = time.strftime(date_format, time.localtime(record.created))

        color = self.COLORS.get(record.levelno, self.reset)
        # 仅给时间和等级加颜色，消息内容不加颜色
        # 直接将时间字符串嵌入格式模板中，避免 logging 模块自动添加毫秒
        log_fmt = f"{color}{current_time}{self.reset} - %(name)s - {color}%(levelname)s{self.reset} - %(message)s"

        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


logger = logging.getLogger("wows-renderer-server")
logger.setLevel(logging.INFO)
# 避免重复添加 handler
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(ColoredFormatter())
    logger.addHandler(ch)

app = FastAPI(title="WoWs Minimap Renderer Service")

# 临时文件目录
TEMP_DIR = Path("/tmp/wows_renderer")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# 渲染器命令 (Docker容器内直接使用安装好的模块)
RENDER_CMD = "python -m render"


def cleanup_files(files: list[Path]):
    """清理临时文件"""
    for file_path in files:
        try:
            if file_path.exists():
                os.remove(file_path)
                logger.info(f"已删除临时文件: {file_path}")
        except Exception as e:
            logger.error(f"删除文件失败 {file_path}: {e}")


@app.get("/")
async def health_check():
    return {"status": "ok", "service": "wows-minimap-renderer"}


@app.post("/render")
async def render_replay(
    background_tasks: BackgroundTasks, replay: UploadFile = File(...)
):
    filename = replay.filename
    if not filename or not filename.endswith(".wowsreplay"):
        raise HTTPException(status_code=400, detail="Invalid file extension")

    request_id = str(uuid.uuid4())
    logger.info(f"收到渲染请求 {request_id} 文件名: {filename}")

    # 1. 保存上传的文件
    input_filename = f"{request_id}_{filename}"
    input_path = TEMP_DIR / input_filename
    # 预期的输出视频路径
    expected_output_path = input_path.with_suffix(".mp4")

    def get_cleanup_files():
        """动态查找所有以 request_id 开头的相关文件"""
        return list(TEMP_DIR.glob(f"{request_id}*"))

    try:
        with input_path.open("wb") as buffer:
            shutil.copyfileobj(replay.file, buffer)
    except Exception as e:
        logger.error(f"保存上传文件失败: {e}")
        raise HTTPException(status_code=500, detail="Failed to save file")

    # 3. 执行渲染命令
    # 这里的命令假设 render 模块已安装在 Python 路径中
    cmd = f"{RENDER_CMD} --replay {input_path}"
    logger.info(f"执行命令: {cmd}")

    try:
        process = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )

        # 设置超时时间 (例如 10 分钟)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
        except asyncio.TimeoutError:
            process.kill()
            cleanup_files(get_cleanup_files())
            raise HTTPException(status_code=504, detail="Rendering timed out")

        if process.returncode != 0:
            error_log = stderr.decode() + stdout.decode()
            logger.error(f"渲染失败: {error_log}")
            cleanup_files(get_cleanup_files())
            raise HTTPException(
                status_code=500, detail=f"Render failed: {error_log[-500:]}"
            )

        if not expected_output_path.exists():
            logger.error("未找到输出视频文件")
            cleanup_files(get_cleanup_files())
            raise HTTPException(status_code=500, detail="Output video file missing")

        logger.info(f"渲染成功: {expected_output_path}")

        # 4. 返回视频文件，并在发送后清理
        # 在添加任务时立即执行 glob 查找当前存在的文件
        background_tasks.add_task(cleanup_files, get_cleanup_files())

        return FileResponse(
            path=expected_output_path,
            filename=f"{Path(filename).stem}.mp4",
            media_type="video/mp4",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("渲染过程中发生意外错误")
        cleanup_files(get_cleanup_files())
        raise HTTPException(status_code=500, detail=str(e))
