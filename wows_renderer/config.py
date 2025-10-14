"""配置模块"""

import nonebot
from pathlib import Path
from pydantic import BaseModel, validator


class Config(BaseModel):
    """战舰世界回放渲染插件的配置类"""

    # minimap_renderer 项目路径
    renderer_project_path: Path

    # 缓存与输出路径
    wows_render_temp_path: Path = Path("cache/wows_render/temp")
    wows_render_output_path: Path = Path("cache/wows_render/output")

    # 渲染相关设置
    render_timeout: int = 600  # 渲染超时时间(秒)
    enable_cleanup: bool = True  # 是否自动清理临时文件

    @validator("renderer_project_path")
    def renderer_path_must_exist(cls, v):
        if not v.exists():
            raise ValueError(f"渲染器路径不存在: {v}")
        return v

    @validator("wows_render_temp_path", "wows_render_output_path")
    def create_path(cls, v):
        v.mkdir(parents=True, exist_ok=True)
        return v


# 创建配置实例
plugin_config = Config.parse_obj(nonebot.get_driver().config.dict())
