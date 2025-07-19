# __init__.py

import asyncio
import uuid
from pathlib import Path
import shutil
import httpx

import nonebot
from .config import Config

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.rule import Rule

# --- 从驱动器中加载配置 ---
# 这一步会读取 .env 文件并填充到我们定义的 Config 模型中
plugin_config = Config.parse_obj(nonebot.get_driver().config.dict())

# --- 配置部分 (不变) ---
TEMP_PATH = Path("cache/wows_render/temp")
OUTPUT_PATH = Path("cache/wows_render/output")
RENDERER_PROJECT_PATH = plugin_config.renderer_project_path
PYTHON_EXECUTABLE = str(RENDERER_PROJECT_PATH / "venv/Scripts/python.exe")
TEMP_PATH.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.mkdir(parents=True, exist_ok=True)


# --- 规则：只响应 .wowsreplay 文件 ---
# 【改回】使用 Rule 来判断文件消息
def is_wows_replay() -> Rule:
    def check(event: GroupMessageEvent) -> bool:
        # 遍历消息段，查找文件类型的消息
        for seg in event.message:
            if seg.type == "file" and seg.data["file"].endswith(".wowsreplay"):
                return True
        return False

    return Rule(check)


# --- 事件响应器 ---
# 【改回】使用 on_message
wows_render_matcher = on_message(rule=is_wows_replay(), priority=10, block=True)


@wows_render_matcher.handle()
async def handle_replay_file(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    # 从消息中提取文件信息
    file_seg = next(seg for seg in event.message if seg.type == "file")
    file_name = file_seg.data["file"]

    # 使用UUID确保文件名唯一
    unique_id = str(uuid.uuid4())
    # 使用原始文件名作为基础，保留其信息
    replay_file_path = TEMP_PATH / f"{unique_id}_{file_name}"
    video_file_path = OUTPUT_PATH / f"{unique_id}.mp4"

    try:
        await matcher.send(
            f"收到回放文件「{file_name}」，正在准备渲染... 请耐心等待，这可能需要几分钟。"
        )

        # 1. 从 go-cqhttp 获取文件下载链接
        file_info = await bot.get_group_file_url(
            group_id=event.group_id, file_id=file_seg.data["file_id"]
        )
        file_url = file_info.get("url")
        if not file_url:
            await matcher.send(
                "无法获取文件下载链接，请检查 go-cqhttp 配置或机器人权限。"
            )
            return

        # 2. 使用 httpx 下载文件
        async with httpx.AsyncClient() as client:
            resp = await client.get(file_url, timeout=60)  # 设置60秒超时
            resp.raise_for_status()
            replay_file_path.write_bytes(resp.content)
        logger.info(f"已保存回放文件至: {replay_file_path}")

        # --- 后续处理逻辑保持不变 ---
        success, output_log = await run_render_process(
            replay_file_path, video_file_path
        )

        if success and video_file_path.exists():
            logger.info(f"渲染成功，视频位于: {video_file_path}")
            await matcher.send(f"「{file_name}」渲染完成！正在上传...")
            video_uri = video_file_path.resolve().as_uri()
            await bot.upload_group_file(
                group_id=event.group_id,
                file=video_uri,
                name=f"{Path(file_name).stem}.mp4",
            )
        else:
            logger.error(f"渲染失败: {file_name}\n日志: {output_log}")
            error_message = f"渲染失败了...\n错误日志 (部分):\n{output_log[-500:]}"
            await matcher.send(f"抱歉，「{file_name}」{error_message}")

    except Exception as e:
        logger.exception("处理回放文件时发生意外错误")
        await matcher.send(f"处理过程中发生未知错误: {e}")

    finally:
        if replay_file_path.exists():
            replay_file_path.unlink()
        if video_file_path.exists():
            video_file_path.unlink()


async def run_render_process(replay_path: Path, output_path: Path) -> tuple[bool, str]:
    command = [
        PYTHON_EXECUTABLE,
        "-m",
        "render",
        "--replay",
        # 【关键修改】使用 .resolve() 获取文件的绝对路径
        str(replay_path.resolve()),
    ]
    logger.info(f"执行渲染命令: {' '.join(command)}")

    # 预测的输出路径逻辑保持不变，因为它基于 cwd，是正确的
    original_video_path = replay_path.with_suffix(".mp4")

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=RENDERER_PROJECT_PATH,
    )
    stdout, stderr = await process.communicate()
    output_log = stdout.decode("utf-8", errors="ignore") + stderr.decode(
        "utf-8", errors="ignore"
    )

    if process.returncode == 0:
        if original_video_path.exists():
            logger.info(f"渲染脚本成功，原始视频位于: {original_video_path}")
            shutil.move(str(original_video_path), str(output_path))
            logger.info(f"已将视频移动到目标路径: {output_path}")
            return True, output_log
        else:
            log = (
                f"渲染进程返回成功，但未在预期路径找到视频文件: {original_video_path}\n"
                + output_log
            )
            logger.error(log)
            return False, log
    else:
        return False, output_log
