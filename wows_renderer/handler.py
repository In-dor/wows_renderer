"""消息处理模块"""

import uuid
from pathlib import Path

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
from nonebot.matcher import Matcher
from nonebot.log import logger

import httpx
import aiofiles

from .renderer import render_replay
from .utils import cleanup_files
from .config import plugin_config

# 从配置中获取路径
TEMP_PATH = plugin_config.wows_render_temp_path
OUTPUT_PATH = plugin_config.wows_render_output_path


async def handle_replay_file(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    """处理战舰世界回放文件"""

    # 从消息中提取文件信息
    file_seg = next((seg for seg in event.message if seg.type == "file"), None)
    if not file_seg:
        await matcher.finish("未检测到回放文件，请重试")

    file_name = file_seg.data.get("file", "unknown.wowsreplay")
    file_id = file_seg.data.get("file_id", "")

    # 生成唯一标识符和文件路径
    unique_id = str(uuid.uuid4())
    replay_file_path = TEMP_PATH / f"{unique_id}_{file_name}"
    video_file_path = OUTPUT_PATH / f"{unique_id}.mp4"

    try:
        await matcher.send(
            f"收到回放文件「{file_name}」，开始准备渲染战局小地图视频...\n⏳ 这可能需要几分钟，请耐心等待"
        )

        # 1. 获取文件下载链接
        try:
            file_info = await bot.get_group_file_url(
                group_id=event.group_id, file_id=file_id
            )
            file_url = file_info.get("url")
            if not file_url:
                await matcher.finish("❌ 无法获取文件下载链接，请检查机器人权限")
        except Exception as e:
            logger.error(f"获取文件URL失败: {e}")
            await matcher.finish("❌ 获取文件下载链接失败，请检查机器人权限或稍后再试")

        # 2. 下载文件
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(file_url, timeout=60)
                resp.raise_for_status()
                async with aiofiles.open(replay_file_path, "wb") as f:
                    await f.write(resp.content)
            logger.info(f"已异步下载回放文件: {replay_file_path}")
        except Exception as e:
            logger.error(f"下载文件失败: {e}")
            await matcher.finish("❌ 下载回放文件失败，请稍后再试")

        # 3. 渲染视频
        await matcher.send("📥 文件下载完成，正在调用 minimap_renderer 进行渲染...")
        success, message, log = await render_replay(replay_file_path, video_file_path)

        # 4. 处理渲染结果
        if success:
            logger.info(f"渲染成功: {file_name}")
            await matcher.send(f"✅ 「{file_name}」渲染完成！正在发送视频...")
            try:
                await matcher.send(MessageSegment.video(video_file_path))
            except Exception as e:
                logger.error(f"发送视频失败: {e}")
                await matcher.finish(
                    "⚠️ 视频渲染成功，但发送失败，请检查机器人权限或联系管理员"
                )
        else:
            logger.error(f"渲染失败: {message}")
            error_log = log[-500:] if log else "无详细日志"
            await matcher.finish(
                f"❌ 抱歉，「{file_name}」渲染失败\n{message}\n\n错误日志:\n{error_log}"
            )

    except Exception as e:
        logger.exception(f"处理回放文件时发生错误: {e}")
        await matcher.finish("❌ 处理过程中发生未知错误，请联系管理员")

    finally:
        # 清理临时文件
        await cleanup_files([replay_file_path, video_file_path])
