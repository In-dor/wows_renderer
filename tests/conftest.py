import tempfile
from pathlib import Path

import nonebot


TEST_ROOT = Path(tempfile.gettempdir()) / "wows-renderer-tests"

nonebot.init(
    renderer_api_endpoint="http://renderer.test",
    wows_render_temp_path=TEST_ROOT / "bot-temp",
    wows_render_output_path=TEST_ROOT / "bot-output",
    max_replay_size_mb=1,
    max_video_size_mb=1,
)
