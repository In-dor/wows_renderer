"""消息处理模块"""

import uuid
from pathlib import Path

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
from nonebot.matcher import Matcher
from nonebot.log import logger
from nonebot.exception import FinishedException

import httpx
import aiofiles

from .renderer import render_replay
from .utils import cleanup_files
from .config import plugin_config

# 从配置中获取路径
TEMP_PATH = plugin_config.wows_render_temp_path
OUTPUT_PATH = plugin_config.wows_render_output_path


class FileTooLargeError(Exception):
    """The downloaded file exceeded its configured size limit."""


async def _download_replay(url: str, destination: Path) -> None:
    max_bytes = plugin_config.max_replay_size_mb * 1024 * 1024
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            content_length = resp.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                raise FileTooLargeError

            downloaded = 0
            async with aiofiles.open(destination, "wb") as f:
                async for chunk in resp.aiter_bytes():
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        raise FileTooLargeError
                    await f.write(chunk)


async def handle_replay_file(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    """处理战舰世界回放文件"""

    # 从消息中提取文件信息
    file_seg = next((seg for seg in event.message if seg.type == "file"), None)
    if not file_seg:
        await matcher.finish("未检测到回放文件，请重试")

    original_file_name = file_seg.data.get("file", "unknown.wowsreplay")
    file_name = Path(original_file_name).name
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
        except Exception as e:
            logger.error(f"获取文件URL失败: {e}")
            await matcher.finish("❌ 获取文件下载链接失败，请检查机器人权限或稍后再试")

        file_url = file_info.get("url")
        if not file_url:
            await matcher.finish("❌ 无法获取文件下载链接，请检查机器人权限")

        # 2. 下载文件
        try:
            await _download_replay(file_url, replay_file_path)
            logger.info(f"已异步下载回放文件: {replay_file_path}")
        except FileTooLargeError:
            logger.warning(f"回放文件超过大小限制: {file_name}")
            await matcher.finish(
                f"❌ 回放文件超过 {plugin_config.max_replay_size_mb} MB 限制"
            )
        except httpx.TimeoutException:
            logger.error(f"下载文件超时: {file_url}")
            await matcher.finish("❌ 下载回放文件超时，请稍后再试")
        except httpx.HTTPStatusError as e:
            logger.error(f"下载文件失败，HTTP 状态码: {e.response.status_code}")
            await matcher.finish(f"❌ 下载回放文件失败 ({e.response.status_code})")
        except Exception as e:
            logger.error(f"下载文件发生未知错误: {e}")
            await matcher.finish("❌ 下载回放文件失败，请稍后再试")

        # 3. 渲染视频
        success, message, log = await render_replay(replay_file_path, video_file_path)

        # 4. 处理渲染结果
        if success:
            logger.info(f"渲染成功: {file_name}")
            max_video_bytes = plugin_config.max_video_size_mb * 1024 * 1024
            if video_file_path.stat().st_size > max_video_bytes:
                await matcher.finish(
                    f"⚠️ 视频超过 {plugin_config.max_video_size_mb} MB，无法发送"
                )
            await matcher.send(f"✅ 「{file_name}」渲染完成！正在发送视频...")
            try:
                # 读取视频内容为 bytes 发送，解决 Docker 容器间路径不互通的问题
                async with aiofiles.open(video_file_path, "rb") as f:
                    video_data = await f.read()
                await matcher.send(MessageSegment.video(video_data))
            except Exception as e:
                logger.error(f"发送视频失败: {e}")
                await matcher.finish(
                    "⚠️ 视频渲染成功，但发送失败，请检查机器人权限或联系管理员"
                )
        else:
            log_tail = log[-2000:] if log else "无详细日志"
            logger.error(f"渲染失败: {message}; 日志: {log_tail}")
            await matcher.finish(f"❌ 抱歉，「{file_name}」渲染失败\n{message}")

    except FinishedException:
        raise
    except Exception as e:
        logger.exception(f"处理回放文件时发生错误: {e}")
        await matcher.finish("❌ 处理过程中发生未知错误，请联系管理员")

    finally:
        # 清理临时文件
        await cleanup_files([replay_file_path, video_file_path])
