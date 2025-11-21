import os
import uuid
import shutil
import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("wows-renderer-server")

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
                logger.info(f"Deleted temp file: {file_path}")
        except Exception as e:
            logger.error(f"Failed to delete {file_path}: {e}")


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
    logger.info(f"Received render request {request_id} for file {filename}")

    # 1. 保存上传的文件
    input_filename = f"{request_id}_{filename}"
    input_path = TEMP_DIR / input_filename

    try:
        with input_path.open("wb") as buffer:
            shutil.copyfileobj(replay.file, buffer)
    except Exception as e:
        logger.error(f"Failed to save upload file: {e}")
        raise HTTPException(status_code=500, detail="Failed to save file")

    # 2. 构建输出路径 (minimap_renderer 默认在同目录下生成 .mp4)
    expected_output_path = input_path.with_suffix(".mp4")

    # 3. 执行渲染命令
    # 这里的命令假设 render 模块已安装在 Python 路径中
    cmd = f"{RENDER_CMD} --replay {input_path}"
    logger.info(f"Executing: {cmd}")

    try:
        process = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )

        # 设置超时时间 (例如 10 分钟)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
        except asyncio.TimeoutError:
            process.kill()
            cleanup_files([input_path])
            raise HTTPException(status_code=504, detail="Rendering timed out")

        if process.returncode != 0:
            error_log = stderr.decode() + stdout.decode()
            logger.error(f"Render failed: {error_log}")
            cleanup_files([input_path])
            raise HTTPException(
                status_code=500, detail=f"Render failed: {error_log[-500:]}"
            )

        if not expected_output_path.exists():
            logger.error("Output video file not found")
            cleanup_files([input_path])
            raise HTTPException(status_code=500, detail="Output video file missing")

        logger.info(f"Render success: {expected_output_path}")

        # 4. 返回视频文件，并在发送后清理
        background_tasks.add_task(cleanup_files, [input_path, expected_output_path])

        return FileResponse(
            path=expected_output_path,
            filename=f"{Path(filename).stem}.mp4",
            media_type="video/mp4",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error during rendering")
        cleanup_files([input_path, expected_output_path])
        raise HTTPException(status_code=500, detail=str(e))
