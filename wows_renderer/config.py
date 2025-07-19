from pathlib import Path
from pydantic import BaseModel


class Config(BaseModel):
    """
    wows_renderer 插件的配置类
    """

    # 定义渲染器项目的根目录路径
    # NoneBot 会自动从 .env 文件中读取 RENDERER_PROJECT_PATH 的值
    renderer_project_path: Path


# Pydantic 会自动处理类型转换，将字符串路径转换为 Path 对象
