"""配置模块"""

import nonebot
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class Config(BaseModel):
    """战舰世界回放渲染插件的配置类"""

    # minimap_renderer 项目路径 (作为工作目录)
    # 如果配置了 renderer_api_endpoint，则此项为可选
    renderer_project_path: Optional[Path] = None

    # 指定 Python 解释器路径 (可选，用于指定外部 venv 或系统 python)
    renderer_python_path: Optional[Path] = None

    # 远程渲染 API 地址 (可选，配置后将优先使用 HTTP 调用)
    renderer_api_endpoint: Optional[str] = None
    renderer_api_token: Optional[str] = None

    # 缓存与输出路径
    wows_render_temp_path: Path = Field(default=Path("cache/wows_render/temp"))
    wows_render_output_path: Path = Field(default=Path("cache/wows_render/output"))

    # 渲染相关设置
    render_timeout: int = Field(default=600, gt=0)  # 渲染超时时间(秒)
    render_fps: int = Field(default=60, gt=0)
    render_speed: float = Field(default=15, gt=0)
    render_resolution: str = "1920x1200"
    render_quality: int = Field(default=8, ge=1, le=10)
    render_interpolation: Literal["native", "blend", "motion", "duplicate"] = (
        "native"
    )
    enable_cleanup: bool = True  # 是否自动清理临时文件
    max_concurrent_renders: int = Field(default=0, ge=0)  # 0为不限制
    max_replay_size_mb: int = Field(default=100, gt=0)
    max_video_size_mb: int = Field(default=300, gt=0)

    @field_validator("renderer_api_endpoint")
    @classmethod
    def normalize_api_endpoint(cls, value: Optional[str]) -> Optional[str]:
        return value.rstrip("/") if value else None

    @field_validator("render_resolution")
    @classmethod
    def validate_render_resolution(cls, value: str) -> str:
        try:
            width, height = map(int, value.lower().split("x", maxsplit=1))
        except ValueError as exc:
            raise ValueError("渲染分辨率必须使用 WIDTHxHEIGHT 格式") from exc
        if width <= 0 or height <= 0 or width % 2 or height % 2:
            raise ValueError("渲染分辨率的宽高必须是正偶数")
        if width * 5 != height * 8:
            raise ValueError("渲染分辨率必须保持 8:5 宽高比")
        return f"{width}x{height}"

    @model_validator(mode="after")
    def check_paths_and_create(self) -> "Config":
        if self.renderer_project_path and not self.renderer_project_path.exists():
            raise ValueError(f"渲染器路径不存在: {self.renderer_project_path}")

        if self.renderer_python_path and not self.renderer_python_path.exists():
            raise ValueError(f"Python解释器路径不存在: {self.renderer_python_path}")

        if not self.renderer_api_endpoint and not self.renderer_project_path:
            raise ValueError(
                "必须配置 renderer_project_path (本地渲染) 或 renderer_api_endpoint (远程渲染)"
            )

        if (
            self.render_interpolation == "native"
            and self.render_fps < self.render_speed
        ):
            raise ValueError("原生插值模式要求 render_fps 不低于 render_speed")

        self.wows_render_temp_path.mkdir(parents=True, exist_ok=True)
        self.wows_render_output_path.mkdir(parents=True, exist_ok=True)
        return self


# 创建配置实例
plugin_config = Config.model_validate(nonebot.get_driver().config.model_dump())
