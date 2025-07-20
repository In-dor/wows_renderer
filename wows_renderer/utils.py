"""工具函数模块"""

from pathlib import Path
from nonebot.log import logger

from .config import plugin_config


async def cleanup_files(file_paths: list[Path]) -> None:
    """清理临时文件"""
    if not plugin_config.enable_cleanup:
        logger.debug("自动清理已禁用，跳过文件清理")
        return

    for path in file_paths:
        try:
            if path.exists():
                path.unlink()
                logger.debug(f"已删除临时文件: {path}")
        except Exception as e:
            logger.error(f"删除文件失败 {path}: {e}")
