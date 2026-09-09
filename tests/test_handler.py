from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from nonebot.exception import FinishedException

from wows_renderer import handler


class FakeMatcher:
    def __init__(self):
        self.sent = []
        self.finished = []

    async def send(self, message):
        self.sent.append(message)

    async def finish(self, message):
        self.finished.append(message)
        raise FinishedException


class FakeBot:
    async def get_group_file_url(self, **_):
        return {"url": "https://files.test/battle.wowsreplay"}


@pytest.mark.asyncio
async def test_finish_control_flow_is_not_rewritten(monkeypatch):
    async def timeout(*_):
        raise httpx.TimeoutException("timeout")

    cleaned = []

    async def cleanup(paths):
        cleaned.extend(paths)

    monkeypatch.setattr(handler, "_download_replay", timeout)
    monkeypatch.setattr(handler, "cleanup_files", cleanup)

    segment = SimpleNamespace(
        type="file",
        data={"file": "battle.wowsreplay", "file_id": "file-id"},
    )
    event = SimpleNamespace(message=[segment], group_id=123)
    matcher = FakeMatcher()

    with pytest.raises(FinishedException):
        await handler.handle_replay_file(FakeBot(), event, matcher)

    assert matcher.finished == ["❌ 下载回放文件超时，请稍后再试"]
    assert len(cleaned) == 3


@pytest.mark.asyncio
async def test_download_rejects_stream_over_limit(monkeypatch, tmp_path: Path):
    class Response:
        headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b"x" * (1024 * 1024 + 1)

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def stream(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(handler.httpx, "AsyncClient", Client)
    destination = tmp_path / "large.wowsreplay"

    with pytest.raises(handler.FileTooLargeError):
        await handler._download_replay("https://files.test/replay", destination)

    assert destination.exists()


@pytest.mark.asyncio
async def test_handle_replay_file_sends_report_then_video(monkeypatch, tmp_path: Path):
    async def fake_download(url, dest):
        dest.write_bytes(b"replay")

    async def fake_report(replay_path, report_path):
        report_path.write_bytes(b"report-png")
        return True, "战报生成成功", ""

    async def fake_render(replay_path, video_path):
        video_path.write_bytes(b"video-mp4")
        return True, "渲染成功", ""

    cleaned = []

    async def fake_cleanup(paths):
        cleaned.extend(paths)

    monkeypatch.setattr(handler, "_download_replay", fake_download)
    monkeypatch.setattr(handler, "render_battle_report", fake_report)
    monkeypatch.setattr(handler, "render_replay", fake_render)
    monkeypatch.setattr(handler, "cleanup_files", fake_cleanup)
    monkeypatch.setattr(handler.plugin_config, "enable_battle_report", True)
    monkeypatch.setattr(handler.plugin_config, "enable_video_render", True)
    monkeypatch.setattr(handler.plugin_config, "render_report_only", False)
    monkeypatch.setattr(handler, "TEMP_PATH", tmp_path)
    monkeypatch.setattr(handler, "OUTPUT_PATH", tmp_path)

    segment = SimpleNamespace(
        type="file",
        data={"file": "battle.wowsreplay", "file_id": "file-id"},
    )
    event = SimpleNamespace(message=[segment], group_id=123)
    matcher = FakeMatcher()

    await handler.handle_replay_file(FakeBot(), event, matcher)

    assert any("率先生成战报长图" in msg for msg in matcher.sent if isinstance(msg, str))
    assert any("正在发送视频" in msg for msg in matcher.sent if isinstance(msg, str))
    # 验证清理了所有 3 个文件
    assert len(cleaned) == 3


@pytest.mark.asyncio
async def test_handle_replay_file_report_only(monkeypatch, tmp_path: Path):
    async def fake_download(url, dest):
        dest.write_bytes(b"replay")

    async def fake_report(replay_path, report_path):
        report_path.write_bytes(b"report-png")
        return True, "战报生成成功", ""

    render_called = False

    async def fake_render(replay_path, video_path):
        nonlocal render_called
        render_called = True
        return True, "渲染成功", ""

    cleaned = []

    async def fake_cleanup(paths):
        cleaned.extend(paths)

    monkeypatch.setattr(handler, "_download_replay", fake_download)
    monkeypatch.setattr(handler, "render_battle_report", fake_report)
    monkeypatch.setattr(handler, "render_replay", fake_render)
    monkeypatch.setattr(handler, "cleanup_files", fake_cleanup)
    monkeypatch.setattr(handler.plugin_config, "enable_battle_report", True)
    monkeypatch.setattr(handler.plugin_config, "render_report_only", True)
    monkeypatch.setattr(handler, "TEMP_PATH", tmp_path)
    monkeypatch.setattr(handler, "OUTPUT_PATH", tmp_path)

    segment = SimpleNamespace(
        type="file",
        data={"file": "battle.wowsreplay", "file_id": "file-id"},
    )
    event = SimpleNamespace(message=[segment], group_id=123)
    matcher = FakeMatcher()

    await handler.handle_replay_file(FakeBot(), event, matcher)

    assert render_called is False
    assert any("正在生成 2.4K 战报全景长图" in msg for msg in matcher.sent if isinstance(msg, str))
    assert len(cleaned) == 3

