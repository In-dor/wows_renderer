"""配置模块"""

import nonebot
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, validator, root_validator


class Config(BaseModel):
    """战舰世界回放渲染插件的配置类"""

    # minimap_renderer 项目路径 (作为工作目录)
    # 如果配置了 renderer_api_endpoint，则此项为可选
    renderer_project_path: Optional[Path] = None

    # 指定 Python 解释器路径 (可选，用于指定外部 venv 或系统 python)
    renderer_python_path: Optional[Path] = None

    # 远程渲染 API 地址 (可选，配置后将优先使用 HTTP 调用)
    renderer_api_endpoint: Optional[str] = None

    # 缓存与输出路径
    wows_render_temp_path: Path = Path("cache/wows_render/temp")
    wows_render_output_path: Path = Path("cache/wows_render/output")

    # 渲染相关设置
    render_timeout: int = 600  # 渲染超时时间(秒)
    enable_cleanup: bool = True  # 是否自动清理临时文件

    @validator("renderer_project_path")
    def renderer_path_must_exist(cls, v):
        if v and not v.exists():
            raise ValueError(f"渲染器路径不存在: {v}")
        return v

    @root_validator
    def check_render_config(cls, values):
        api_endpoint = values.get("renderer_api_endpoint")
        project_path = values.get("renderer_project_path")

        if not api_endpoint and not project_path:
            raise ValueError("必须配置 renderer_project_path (本地渲染) 或 renderer_api_endpoint (远程渲染)")
        return values

    @validator("renderer_python_path")
    def python_path_must_exist(cls, v):
        if v and not v.exists():
            raise ValueError(f"Python解释器路径不存在: {v}")
        return v

    @validator("wows_render_temp_path", "wows_render_output_path")
    def create_path(cls, v):
        v.mkdir(parents=True, exist_ok=True)
        return v


# 创建配置实例
plugin_config = Config.parse_obj(nonebot.get_driver().config.dict())
