"""配置模块"""

from pathlib import Path
from pydantic import BaseModel, validator


class Config(BaseModel):
    """战舰世界回放渲染插件的配置类"""

    # minimap_renderer 项目路径
    renderer_project_path: Path

    # 渲染相关设置
    render_timeout: int = 600  # 渲染超时时间(秒)
    enable_cleanup: bool = True  # 是否自动清理临时文件

    @validator("renderer_project_path")
    def path_must_exist(cls, v):
        if not v.exists():
            raise ValueError(f"渲染器路径不存在: {v}")
        return v
