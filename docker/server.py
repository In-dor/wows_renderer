import os
import secrets
import signal
import sys
import time
import uuid
import shutil
import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse
from starlette.responses import JSONResponse


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
TEMP_DIR = Path(os.getenv("WOWS_RENDER_TEMP_DIR", "/tmp/wows_renderer"))
TEMP_DIR.mkdir(parents=True, exist_ok=True)


def positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, default))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


# 并发限制
try:
    MAX_CONCURRENT_RENDERS = int(os.getenv("MAX_CONCURRENT_RENDERS", 0))
except ValueError as exc:
    raise RuntimeError("MAX_CONCURRENT_RENDERS must be an integer") from exc
if MAX_CONCURRENT_RENDERS < 0:
    raise RuntimeError("MAX_CONCURRENT_RENDERS cannot be negative")

RENDER_TIMEOUT = positive_int_env("RENDER_TIMEOUT", 600)
MAX_UPLOAD_BYTES = positive_int_env("MAX_REPLAY_SIZE_MB", 100) * 1024 * 1024
API_TOKEN = os.getenv("RENDERER_API_TOKEN")
render_semaphore = (
    asyncio.Semaphore(MAX_CONCURRENT_RENDERS) if MAX_CONCURRENT_RENDERS > 0 else None
)


class RequestBodyTooLarge(Exception):
    pass


class MaxBodySizeMiddleware:
    """Reject oversized request bodies before multipart parsing."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/render":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length and int(content_length) > self.max_bytes:
            await JSONResponse({"detail": "Replay file is too large"}, status_code=413)(
                scope, receive, send
            )
            return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLarge:
            await JSONResponse({"detail": "Replay file is too large"}, status_code=413)(
                scope, receive, send
            )


app.add_middleware(
    MaxBodySizeMiddleware,
    max_bytes=MAX_UPLOAD_BYTES + 1024 * 1024,
)


def cleanup_request_dir(request_dir: Path):
    """Remove all files owned by one render request."""
    try:
        shutil.rmtree(request_dir, ignore_errors=False)
        logger.info(f"已清理请求目录: {request_dir.name}")
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.error(f"删除请求目录失败 {request_dir}: {e}")


def read_log_tail(log_path: Path, limit: int = 4000) -> str:
    with log_path.open("rb") as log_file:
        log_file.seek(0, os.SEEK_END)
        log_file.seek(max(0, log_file.tell() - limit))
        return log_file.read().decode("utf-8", errors="replace")


def write_terminal_output(data: bytes) -> None:
    stream = getattr(sys.stderr, "buffer", sys.stderr)
    try:
        stream.write(data)
    except TypeError:
        stream.write(data.decode("utf-8", errors="replace"))
    stream.flush()


async def relay_process_output(
    stream: asyncio.StreamReader, log_file, request_id: str
) -> None:
    """Tee renderer output to its failure log and the container terminal."""
    prefix = f"[render:{request_id[:8]}] ".encode()
    needs_prefix = True

    while chunk := await stream.read(4096):
        log_file.write(chunk)
        log_file.flush()
        terminal_data = bytearray()
        for value in chunk:
            if needs_prefix and value not in (10, 13):
                terminal_data.extend(prefix)
                needs_prefix = False
            terminal_data.append(value)
            if value in (10, 13):
                needs_prefix = True
        write_terminal_output(bytes(terminal_data))


async def terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if sys.platform == "win32":
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        process.kill()
    finally:
        await process.wait()


def verify_token(authorization: Optional[str]) -> None:
    if not API_TOKEN:
        return
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token, API_TOKEN):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )


def build_render_options(
    fps: int,
    speed: float,
    resolution: str,
    quality: int,
    interpolation: str,
    codec: str,
    encoder: str,
) -> list[str]:
    if fps <= 0:
        raise HTTPException(
            status_code=422, detail="fps must be greater than zero"
        )
    if speed <= 0:
        raise HTTPException(
            status_code=422, detail="speed must be greater than zero"
        )
    if quality < 1 or quality > 10:
        raise HTTPException(
            status_code=422, detail="quality must be between 1 and 10"
        )
    if interpolation not in {"native", "blend", "motion", "duplicate"}:
        raise HTTPException(status_code=422, detail="Invalid interpolation mode")
    if codec not in {"h264", "h265", "av1"}:
        raise HTTPException(status_code=422, detail="Invalid video codec")
    if encoder not in {"auto", "cpu", "nvenc", "qsv", "amf"}:
        raise HTTPException(status_code=422, detail="Invalid video encoder")

    try:
        width, height = map(int, resolution.lower().split("x", maxsplit=1))
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="resolution must use WIDTHxHEIGHT format",
        ) from exc
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise HTTPException(
            status_code=422,
            detail="resolution dimensions must be positive even numbers",
        )
    if width * 5 != height * 8:
        raise HTTPException(
            status_code=422,
            detail="resolution must preserve the 8:5 aspect ratio",
        )
    if interpolation == "native" and fps < speed:
        raise HTTPException(
            status_code=422,
            detail="native interpolation requires fps to be at least speed",
        )

    return [
        "--fps",
        str(fps),
        "--speed",
        str(speed),
        "--resolution",
        f"{width}x{height}",
        "--quality",
        str(quality),
        "--interpolation",
        interpolation,
        "--codec",
        codec,
        "--encoder",
        encoder,
    ]


@app.get("/")
async def health_check():
    return {"status": "ok", "service": "wows-minimap-renderer"}


@app.post("/render")
async def render_replay(
    background_tasks: BackgroundTasks,
    replay: UploadFile = File(...),
    fps: int = Form(60),
    speed: float = Form(15),
    resolution: str = Form("1920x1200"),
    quality: int = Form(8),
    interpolation: str = Form("native"),
    codec: str = Form("h264"),
    encoder: str = Form("auto"),
    authorization: Optional[str] = Header(default=None),
    content_length: Optional[int] = Header(default=None),
):
    verify_token(authorization)
    render_options = build_render_options(
        fps, speed, resolution, quality, interpolation, codec, encoder
    )
    if content_length and content_length > MAX_UPLOAD_BYTES + 1024 * 1024:
        raise HTTPException(status_code=413, detail="Replay file is too large")

    filename = replay.filename
    if not filename or not filename.lower().endswith(".wowsreplay"):
        raise HTTPException(status_code=400, detail="Invalid file extension")

    filename_base = os.path.basename(filename)
    request_id = str(uuid.uuid4())
    request_dir = TEMP_DIR / request_id

    logger.info(f"收到渲染请求 {request_id} 文件名: {filename_base}")

    async def _perform_render():
        request_dir.mkdir(mode=0o700)
        input_path = request_dir / "input.wowsreplay"
        expected_output_path = input_path.with_suffix(".mp4")
        log_path = request_dir / "renderer.log"

        try:
            uploaded = 0
            with input_path.open("wb") as buffer:
                while chunk := await replay.read(1024 * 1024):
                    uploaded += len(chunk)
                    if uploaded > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413, detail="Replay file is too large"
                        )
                    buffer.write(chunk)
        except asyncio.CancelledError:
            cleanup_request_dir(request_dir)
            raise
        except Exception as e:
            if isinstance(e, HTTPException):
                cleanup_request_dir(request_dir)
                raise
            logger.error(f"保存上传文件失败: {e}")
            cleanup_request_dir(request_dir)
            raise HTTPException(status_code=500, detail="Failed to save file")

        command = [
            sys.executable,
            "-m",
            "render",
            "--replay",
            str(input_path),
            *render_options,
        ]
        logger.info(f"执行渲染请求: {request_id}")

        try:
            process = None
            output_task = None
            with log_path.open("wb") as log_file:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    start_new_session=True,
                )
                if process.stdout is None:
                    raise RuntimeError("Renderer process output is unavailable")
                output_task = asyncio.create_task(
                    relay_process_output(process.stdout, log_file, request_id)
                )
                try:
                    await asyncio.wait_for(process.wait(), timeout=RENDER_TIMEOUT)
                except asyncio.TimeoutError:
                    await terminate_process_tree(process)
                    await output_task
                    cleanup_request_dir(request_dir)
                    logger.error(f"渲染超时: {request_id}")
                    raise HTTPException(status_code=504, detail="Rendering timed out")
                await output_task

            if process.returncode != 0:
                error_log = await asyncio.to_thread(read_log_tail, log_path)
                logger.error(f"渲染失败 {request_id}: {error_log}")
                cleanup_request_dir(request_dir)
                raise HTTPException(status_code=500, detail="Render failed")

            if not expected_output_path.exists():
                logger.error(f"未找到输出视频文件: {request_id}")
                cleanup_request_dir(request_dir)
                raise HTTPException(status_code=500, detail="Output video file missing")

            logger.info(f"渲染成功: {request_id}")
            background_tasks.add_task(cleanup_request_dir, request_dir)

            return FileResponse(
                path=expected_output_path,
                filename=f"{Path(filename_base).stem}.mp4",
                media_type="video/mp4",
            )

        except asyncio.CancelledError:
            if process and process.returncode is None:
                await asyncio.shield(terminate_process_tree(process))
            if output_task:
                await asyncio.shield(output_task)
            cleanup_request_dir(request_dir)
            raise
        except HTTPException:
            raise
        except Exception:
            logger.exception(f"渲染过程中发生意外错误: {request_id}")
            cleanup_request_dir(request_dir)
            raise HTTPException(status_code=500, detail="Internal rendering error")

    if render_semaphore:
        async with render_semaphore:
            return await _perform_render()
    else:
        return await _perform_render()
