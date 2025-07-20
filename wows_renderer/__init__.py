"""
战舰世界小地图回放渲染插件
用于接收群聊中的.wowsreplay文件并渲染成战局小地图视频
使用 minimap_renderer 作为后端渲染引擎
"""

import nonebot
from pathlib import Path
from nonebot import on_message
from nonebot.rule import Rule
from nonebot.adapters.onebot.v11 import GroupMessageEvent

from .config import Config
from .handler import handle_replay_file

# 加载配置
plugin_config = Config.parse_obj(nonebot.get_driver().config.dict())

# 确保缓存目录存在
TEMP_PATH = Path("cache/wows_render/temp")
OUTPUT_PATH = Path("cache/wows_render/output")
TEMP_PATH.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.mkdir(parents=True, exist_ok=True)


# 规则：只响应 .wowsreplay 文件
def is_wows_replay() -> Rule:
    async def check(event: GroupMessageEvent) -> bool:
        for seg in event.message:
            if seg.type == "file" and seg.data.get("file", "").endswith(".wowsreplay"):
                return True
        return False

    return Rule(check)


# 注册消息处理器
wows_render_matcher = on_message(rule=is_wows_replay(), priority=10, block=True)
wows_render_matcher.handle()(handle_replay_file)
