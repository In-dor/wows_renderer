import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, UploadFile
from fastapi.testclient import TestClient

from docker import server


def test_body_limit_runs_before_endpoint():
    app = FastAPI()
    app.add_middleware(server.MaxBodySizeMiddleware, max_bytes=5)

    @app.post("/render")
    async def endpoint(request: Request):
        await request.body()
        return {"status": "unexpected"}

    response = TestClient(app).post(
        "/render", content=(chunk for chunk in (b"too-", b"large"))
    )

    assert response.status_code == 413


def test_verify_token(monkeypatch):
    monkeypatch.setattr(server, "API_TOKEN", "expected-token")

    with pytest.raises(HTTPException) as exc_info:
        server.verify_token("Bearer wrong-token")

    assert exc_info.value.status_code == 401
    server.verify_token("Bearer expected-token")


@pytest.mark.asyncio
async def test_render_uses_private_request_directory(
    monkeypatch, tmp_path: Path, capsys
):
    request_id = "6b050938-d99c-4a85-86c7-6238a1278b91"
    monkeypatch.setattr(server, "TEMP_DIR", tmp_path)
    monkeypatch.setattr(server.uuid, "uuid4", lambda: request_id)
    monkeypatch.setattr(server, "API_TOKEN", None)

    captured = {}

    class Process:
        returncode = None
        pid = 42

        def __init__(self):
            self.stdout = server.asyncio.StreamReader()
            self.stdout.feed_data(
                b"\r 50%|#####     | 5/10 [00:01<00:01, 5.00it/s]"
            )
            self.stdout.feed_eof()

        async def wait(self):
            Path(captured["command"][4]).with_suffix(".mp4").write_bytes(b"video")
            self.returncode = 0

    async def create_process(*command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(server.asyncio, "create_subprocess_exec", create_process)
    replay = UploadFile(
        file=BytesIO(b"replay-data"), filename="client-id_battle.wowsreplay"
    )
    background_tasks = BackgroundTasks()

    response = await server.render_replay(
        background_tasks,
        replay,
        fps=30,
        speed=15,
        resolution="1360x850",
        quality=7,
        interpolation="duplicate",
        authorization=None,
        content_length=None,
    )

    request_dir = tmp_path / request_id
    assert Path(response.path) == request_dir / "input.mp4"
    terminal_output = capsys.readouterr().err
    assert "[render:6b050938]" in terminal_output
    assert "50%" in terminal_output
    assert "5.00it/s" in terminal_output
    assert captured["kwargs"]["stdout"] == server.asyncio.subprocess.PIPE
    assert captured["command"][4] == str(request_dir / "input.wowsreplay")
    assert captured["command"][-10:] == (
        "--fps",
        "30",
        "--speed",
        "15",
        "--resolution",
        "1360x850",
        "--quality",
        "7",
        "--interpolation",
        "duplicate",
    )
    assert (request_dir / "input.wowsreplay").read_bytes() == b"replay-data"

    await background_tasks()
    assert not request_dir.exists()


@pytest.mark.asyncio
async def test_cancelled_render_terminates_and_cleans(monkeypatch, tmp_path: Path):
    request_id = "2f3285fb-feb8-458a-a998-fd4fe51e041c"
    monkeypatch.setattr(server, "TEMP_DIR", tmp_path)
    monkeypatch.setattr(server.uuid, "uuid4", lambda: request_id)
    monkeypatch.setattr(server, "API_TOKEN", None)

    class Process:
        returncode = None
        pid = 42

        def __init__(self):
            self.stdout = server.asyncio.StreamReader()
            self.stdout.feed_eof()

        async def wait(self):
            raise asyncio.CancelledError

    async def create_process(*_args, **_kwargs):
        return Process()

    terminated = []

    async def terminate(process):
        terminated.append(process.pid)
        process.returncode = -9

    monkeypatch.setattr(server.asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(server, "terminate_process_tree", terminate)
    replay = UploadFile(file=BytesIO(b"replay-data"), filename="battle.wowsreplay")

    with pytest.raises(asyncio.CancelledError):
        await server.render_replay(
            BackgroundTasks(),
            replay,
            fps=60,
            speed=15,
            resolution="1920x1200",
            quality=8,
            interpolation="native",
            authorization=None,
            content_length=None,
        )

    assert terminated == [42]
    assert not (tmp_path / request_id).exists()


@pytest.mark.parametrize(
    ("options", "detail"),
    [
        ((15, 30, "1920x1200", 8, "native"), "at least speed"),
        ((60, 15, "1920x1080", 8, "native"), "8:5"),
        ((60, 15, "1920x1200", 11, "native"), "between 1 and 10"),
    ],
)
def test_render_option_validation(options, detail):
    with pytest.raises(HTTPException) as exc_info:
        server.build_render_options(*options)

    assert exc_info.value.status_code == 422
    assert detail in exc_info.value.detail
