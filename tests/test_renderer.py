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
    assert kwargs["data"] == {
        "fps": "60",
        "speed": "15",
        "resolution": "1920x1200",
        "quality": "8",
        "interpolation": "native",
    }


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


@pytest.mark.asyncio
async def test_local_render_passes_upstream_options(
    monkeypatch, tmp_path: Path, capsys
):
    replay = tmp_path / "battle.wowsreplay"
    output = tmp_path / "result.mp4"
    replay.write_bytes(b"replay")
    captured = {}

    class Process:
        returncode = None
        pid = 42

        def __init__(self):
            self.stdout = renderer.asyncio.StreamReader()
            self.stdout.feed_data(
                b"\r 50%|#####     | 5/10 [00:01<00:01, 5.00it/s]"
            )
            self.stdout.feed_eof()

        async def wait(self):
            replay.with_suffix(".mp4").write_bytes(b"video")
            self.returncode = 0

    async def create_process(*command, **kwargs):
        captured["command"] = list(command)
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(renderer.plugin_config, "renderer_api_endpoint", None)
    monkeypatch.setattr(renderer, "PYTHON_EXECUTABLE", Path("/usr/bin/python3"))
    monkeypatch.setattr(renderer, "RENDERER_PROJECT_PATH", tmp_path)
    monkeypatch.setattr(renderer.asyncio, "create_subprocess_exec", create_process)

    success, _, _ = await renderer._do_render_replay(replay, output)

    assert success is True
    assert output.read_bytes() == b"video"
    terminal_output = capsys.readouterr().err
    assert "[render:battle]" in terminal_output
    assert "50%" in terminal_output
    assert "5.00it/s" in terminal_output
    assert captured["kwargs"]["stdout"] == renderer.asyncio.subprocess.PIPE
    assert captured["command"][-10:] == [
        "--fps",
        "60",
        "--speed",
        "15",
        "--resolution",
        "1920x1200",
        "--quality",
        "8",
        "--interpolation",
        "native",
    ]
