from pathlib import Path

import pytest

from wows_renderer import renderer


class FakeResponse:
    def __init__(self, chunks, status_code=200, body=b""):
        self.chunks = chunks
        self.status_code = status_code
        self.headers = {}
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def aiter_bytes(self):
        for chunk in self.chunks:
            yield chunk

    async def aread(self):
        return self.body


class FakeClient:
    response = None
    request = None

    def __init__(self, **_):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    def stream(self, method, url, **kwargs):
        type(self).request = (method, url, kwargs)
        return type(self).response


@pytest.mark.asyncio
async def test_remote_render_streams_output(monkeypatch, tmp_path: Path):
    replay = tmp_path / "battle.wowsreplay"
    output = tmp_path / "battle.mp4"
    replay.write_bytes(b"replay")
    FakeClient.response = FakeResponse([b"video-", b"data"])

    monkeypatch.setattr(renderer.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(renderer.plugin_config, "renderer_api_token", "secret")

    result = await renderer._do_render_replay(replay, output)

    assert result[0] is True
    assert output.read_bytes() == b"video-data"
    assert not output.with_suffix(".mp4.part").exists()
    method, url, kwargs = FakeClient.request
    assert (method, url) == ("POST", "http://renderer.test/render")
    assert kwargs["headers"] == {"Authorization": "Bearer secret"}


@pytest.mark.asyncio
async def test_remote_render_removes_oversized_partial(monkeypatch, tmp_path: Path):
    replay = tmp_path / "battle.wowsreplay"
    output = tmp_path / "battle.mp4"
    replay.write_bytes(b"replay")
    FakeClient.response = FakeResponse([b"x" * (1024 * 1024 + 1)])

    monkeypatch.setattr(renderer.httpx, "AsyncClient", FakeClient)

    success, message, _ = await renderer._do_render_replay(replay, output)

    assert success is False
    assert "超过大小限制" in message
    assert not output.exists()
    assert not output.with_suffix(".mp4.part").exists()
