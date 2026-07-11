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
    assert len(cleaned) == 2


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
