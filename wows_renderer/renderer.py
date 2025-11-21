"""渲染器交互模块 - 专用于 minimap_renderer"""

import sys
import asyncio
import aiofiles.os
from pathlib import Path
import httpx
from nonebot.log import logger

from .config import plugin_config

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
        # 否则根据操作系统在项目目录下寻找默认 venv
        if sys.platform == "win32":
            PYTHON_EXECUTABLE = (
                RENDERER_PROJECT_PATH / "venv" / "Scripts" / "python.exe"
            )
        else:
            PYTHON_EXECUTABLE = RENDERER_PROJECT_PATH / "venv" / "bin" / "python"


async def render_replay(replay_path: Path, output_path: Path) -> tuple[bool, str, str]:
    """
    使用 minimap_renderer 处理回放文件 (支持本地或远程调用)

    Args:
        replay_path: 回放文件路径
        output_path: 输出视频路径

    Returns:
        (成功标志, 消息, 日志)
    """

    # 1. 远程渲染模式
    if plugin_config.renderer_api_endpoint:
        logger.info(f"使用远程渲染服务: {plugin_config.renderer_api_endpoint}")
        try:
            async with httpx.AsyncClient(
                timeout=plugin_config.render_timeout
            ) as client:
                with open(replay_path, "rb") as f:
                    files = {
                        "replay": (replay_path.name, f, "application/octet-stream")
                    }
                    resp = await client.post(
                        f"{plugin_config.renderer_api_endpoint}/render", files=files
                    )

                if resp.status_code == 200:
                    async with aiofiles.open(output_path, "wb") as out_f:
                        await out_f.write(resp.content)
                    return True, "远程渲染成功", "Remote render success"
                else:
                    error_msg = f"远程渲染失败: {resp.status_code} - {resp.text}"
                    return False, error_msg, error_msg
        except Exception as e:
            logger.exception(f"远程渲染异常: {e}")
            return False, f"远程渲染服务连接失败: {e}", str(e)

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

    logger.info(f"执行渲染命令: {' '.join(command)}")

    # 预期的渲染输出路径 (minimap_renderer的默认输出方式)
    original_video_path = replay_path.with_suffix(".mp4")

    try:
        # 执行渲染进程
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=RENDERER_PROJECT_PATH,
        )

        # 设置超时
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=plugin_config.render_timeout
            )
            output_log = stdout.decode("utf-8", errors="ignore") + stderr.decode(
                "utf-8", errors="ignore"
            )
        except asyncio.TimeoutError:
            try:
                process.kill()
            except Exception:
                pass
            return False, "渲染超时，已中止处理", "Rendering process timeout"

        # 检查进程返回值
        if process.returncode == 0:
            if original_video_path.exists():
                logger.info(f"渲染成功，原始视频位于: {original_video_path}")
                await aiofiles.os.rename(original_video_path, output_path)
                logger.info(f"已异步将视频移动到目标路径: {output_path}")
                return True, "渲染成功", output_log
            else:
                return False, "渲染进程返回成功，但未找到输出视频", output_log
        else:
            return False, f"渲染进程返回错误 (代码: {process.returncode})", output_log

    except Exception as e:
        logger.exception(f"渲染过程异常: {e}")
        return False, f"渲染过程发生异常: {e}", str(e)
