import os
import subprocess
from pathlib import Path

import psycopg
import pytest


@pytest.fixture(scope="session", autouse=True)
def require_test_database():
    url = os.environ.get("PRISM_TEST_DATABASE_URL")
    if not url or not url.endswith("/prism_test"):
        pytest.skip("Set PRISM_TEST_DATABASE_URL to the disposable prism_test database")
    os.environ["PRISM_DATABASE_URL"] = url


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    from fastapi.testclient import TestClient

    from prism.config import get_settings
    from prism.main import app

    monkeypatch.setenv("PRISM_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        db.execute("TRUNCATE videos, pgqueuer, pgqueuer_log RESTART IDENTITY CASCADE")
    with TestClient(app) as client:
        yield client, tmp_path
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def sample_mp4(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:r=25",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(path),
        ],
        check=True,
        timeout=15,
    )
    return path
