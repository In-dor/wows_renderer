"""渲染器交互模块 - 专用于 minimap_renderer"""

import asyncio
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import aiofiles
import httpx
from nonebot.log import logger

from .config import plugin_config

# 并发限制信号量
render_semaphore = (
    asyncio.Semaphore(plugin_config.max_concurrent_renders)
    if plugin_config.max_concurrent_renders > 0
    else None
)

# 根据配置构建路径 (仅在本地模式下使用)
RENDERER_PROJECT_PATH = (
    Path(plugin_config.renderer_project_path)
    if plugin_config.renderer_project_path
    else None
)

# 确定 Python 解释器路径 (仅本地模式需要)
PYTHON_EXECUTABLE = None
if not plugin_config.renderer_api_endpoint and RENDERER_PROJECT_PATH:
    if plugin_config.renderer_python_path:
        # 如果配置中指定了 Python 路径，则优先使用
        PYTHON_EXECUTABLE = Path(plugin_config.renderer_python_path)
    else:
        # 优先使用项目 venv，不存在时回退到当前解释器
        if sys.platform == "win32":
            venv_python = RENDERER_PROJECT_PATH / "venv" / "Scripts" / "python.exe"
        else:
            venv_python = RENDERER_PROJECT_PATH / "venv" / "bin" / "python"
        PYTHON_EXECUTABLE = (
            venv_python if venv_python.exists() else Path(sys.executable)
        )


def _render_options() -> dict[str, str]:
    return {
        "fps": str(plugin_config.render_fps),
        "speed": str(plugin_config.render_speed),
        "resolution": plugin_config.render_resolution,
        "quality": str(plugin_config.render_quality),
        "interpolation": plugin_config.render_interpolation,
        "codec": plugin_config.render_codec,
        "encoder": plugin_config.render_encoder,
    }


def _append_render_options(command: list[str]) -> None:
    for name, value in _render_options().items():
        command.extend((f"--{name}", value))


def _write_terminal_output(data: bytes) -> None:
    stream = getattr(sys.stderr, "buffer", sys.stderr)
    try:
        stream.write(data)
    except TypeError:
        stream.write(data.decode("utf-8", errors="replace"))
    stream.flush()


async def _relay_process_output(
    stream: asyncio.StreamReader, log_file, label: str
) -> None:
    """Tee renderer output to its failure log and the live terminal."""
    prefix = f"[render:{label}] ".encode()
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
        _write_terminal_output(bytes(terminal_data))


async def _do_render_replay(
    replay_path: Path, output_path: Path
) -> tuple[bool, str, str]:
    """
    使用 minimap_renderer 处理回放文件 (内部函数)
    """
    # 1. 远程渲染模式
    if plugin_config.renderer_api_endpoint:
        logger.info(f"使用远程渲染服务: {plugin_config.renderer_api_endpoint}")
        partial_output_path = output_path.with_suffix(f"{output_path.suffix}.part")
        try:
            headers = {}
            if plugin_config.renderer_api_token:
                headers["Authorization"] = f"Bearer {plugin_config.renderer_api_token}"
            async with httpx.AsyncClient(
                timeout=plugin_config.render_timeout
            ) as client:
                with open(replay_path, "rb") as f:
                    files = {
                        "replay": (replay_path.name, f, "application/octet-stream")
                    }
                    async with client.stream(
                        "POST",
                        f"{plugin_config.renderer_api_endpoint}/render",
                        files=files,
                        data=_render_options(),
                        headers=headers,
                    ) as resp:
                        if resp.status_code != 200:
                            body = (await resp.aread()).decode(
                                "utf-8", errors="replace"
                            )[-500:]
                            return (
                                False,
                                f"远程渲染失败 (HTTP {resp.status_code})",
                                body,
                            )

                        max_bytes = plugin_config.max_video_size_mb * 1024 * 1024
                        content_length = resp.headers.get("content-length")
                        if content_length and int(content_length) > max_bytes:
                            return False, "远程渲染结果超过大小限制", ""

                        written = 0
                        async with aiofiles.open(partial_output_path, "wb") as out_f:
                            async for chunk in resp.aiter_bytes():
                                written += len(chunk)
                                if written > max_bytes:
                                    return False, "远程渲染结果超过大小限制", ""
                                await out_f.write(chunk)

            await asyncio.to_thread(os.replace, partial_output_path, output_path)
            return True, "远程渲染成功", "Remote render success"
        except Exception as e:
            logger.exception(f"远程渲染异常: {e}")
            return False, "远程渲染服务连接失败", str(e)
        finally:
            if partial_output_path.exists():
                await asyncio.to_thread(partial_output_path.unlink)

    # 2. 本地渲染模式
    # 确保解释器存在
    if not PYTHON_EXECUTABLE or not PYTHON_EXECUTABLE.exists():
        return False, f"渲染器Python解释器不存在: {PYTHON_EXECUTABLE}", ""

    # 构建渲染命令 - 基于minimap_renderer的命令行接口
    command = [
        str(PYTHON_EXECUTABLE),
        "-m",
        "render",
        "--replay",
        str(replay_path.resolve()),
    ]
    _append_render_options(command)

    logger.info(f"执行渲染命令: {' '.join(command)}")

    # 预期的渲染输出路径 (minimap_renderer的默认输出方式)
    original_video_path = replay_path.with_suffix(".mp4")
    log_path = output_path.with_suffix(".render.log")
    process = None
    output_task = None

    try:
        # 执行渲染进程
        process_kwargs = {}
        if sys.platform == "win32":
            process_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            process_kwargs["start_new_session"] = True

        with log_path.open("wb") as log_file:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=RENDERER_PROJECT_PATH,
                **process_kwargs,
            )
            if process.stdout is None:
                raise RuntimeError("无法读取渲染器进程输出")
            output_task = asyncio.create_task(
                _relay_process_output(process.stdout, log_file, replay_path.stem)
            )
            try:
                await asyncio.wait_for(
                    process.wait(), timeout=plugin_config.render_timeout
                )
            except asyncio.TimeoutError:
                await _terminate_process_tree(process)
                await output_task
                return False, "渲染超时，已中止处理", "Rendering process timeout"
            await output_task

        output_log = await asyncio.to_thread(_read_log_tail, log_path)

        # 检查进程返回值
        if process.returncode == 0:
            if original_video_path.exists():
                logger.info(f"渲染成功，原始视频位于: {original_video_path}")
                await asyncio.to_thread(shutil.move, original_video_path, output_path)
                logger.info(f"已异步将视频移动到目标路径: {output_path}")
                return True, "渲染成功", output_log
            else:
                return False, "渲染进程返回成功，但未找到输出视频", output_log
        else:
            return False, f"渲染进程返回错误 (代码: {process.returncode})", output_log

    except Exception as e:
        logger.exception(f"渲染过程异常: {e}")
        return False, "渲染过程发生异常", str(e)
    except asyncio.CancelledError:
        if process and process.returncode is None:
            await asyncio.shield(_terminate_process_tree(process))
        if output_task:
            await asyncio.shield(output_task)
        raise
    finally:
        if log_path.exists():
            await asyncio.to_thread(log_path.unlink)


def _read_log_tail(log_path: Path, limit: int = 64 * 1024) -> str:
    with log_path.open("rb") as log_file:
        log_file.seek(0, os.SEEK_END)
        log_file.seek(max(0, log_file.tell() - limit))
        return log_file.read().decode("utf-8", errors="replace")


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    """Terminate a timed-out renderer and wait for its resources to be reaped."""
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


async def render_replay(replay_path: Path, output_path: Path) -> tuple[bool, str, str]:
    """
    使用 minimap_renderer 处理回放文件 (支持本地或远程调用)

    Args:
        replay_path: 回放文件路径
        output_path: 输出视频路径

    Returns:
        (成功标志, 消息, 日志)
    """
    if render_semaphore:
        async with render_semaphore:
            return await _do_render_replay(replay_path, output_path)
    else:
        return await _do_render_replay(replay_path, output_path)
