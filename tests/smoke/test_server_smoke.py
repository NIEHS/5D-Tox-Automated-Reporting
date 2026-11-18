"""End-to-end smoke, non-interactive (independent review, 2026-11-16): the real
server, started as its own process on an empty sessions directory, takes a
.zip of study files over HTTP and serves the study's derived workflow state.

No browser and no page.pause(): this is the regression gate CI runs on every
push and pull request (the Playwright walkthrough in tests/e2e stays manual)."""

import io
import os
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

REPO = Path(__file__).resolve().parents[2]
DTX = "DTXSID50469320"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(tmp_path):
    port = _free_port()
    env = {**os.environ, "SESSIONS_DIR": str(tmp_path / "sessions"),
           "OUTPUT_DIR": str(tmp_path / "output")}
    (tmp_path / "sessions").mkdir()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "web_routes.background_server:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 90
    while time.time() < deadline:
        if proc.poll() is not None:
            pytest.fail(f"server exited: {proc.stdout.read().decode()[-2000:]}")
        try:
            urllib.request.urlopen(f"{base}/api/workflow/{DTX}/state", timeout=2)
            break
        except OSError:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("server did not start within 90 s")
    yield base, tmp_path
    proc.terminate()
    proc.wait(timeout=20)


def _post_zip(url: str, data: bytes) -> tuple[int, bytes]:
    boundary = "smokeboundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"pool.zip\"\r\nContent-Type: application/zip\r\n\r\n").encode() \
        + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_the_server_takes_files_and_serves_derived_state(server):
    base, tmp = server
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("study/body_weight.csv", "Animal,1,2\nDose,0,10\nBody Weight,250,240\n")
    status, body = _post_zip(f"{base}/api/upload-zip?dtxsid={DTX}", buf.getvalue())
    assert status == 200, body[:500]
    assert (tmp / "sessions" / DTX / "files" / "body_weight.csv").exists()

    with urllib.request.urlopen(f"{base}/api/workflow/{DTX}/state", timeout=30) as r:
        assert r.status == 200
        assert b"phase" in r.read()
