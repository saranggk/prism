"""Visual indexing can fail and retry without losing a ready transcript."""

import os
from uuid import uuid4

import numpy as np
import psycopg


def test_failed_visual_index_is_retryable_and_idempotent(api, monkeypatch):
    from prism import worker

    client, tmp_path = api
    video_id = uuid4()
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        db.execute(
            "INSERT INTO videos (id, title, source_path, duration_seconds, "
            "status, transcript_state) "
            "VALUES (%s, 'Demo', %s, 10, 'ready', 'present')",
            (video_id, str(tmp_path / "demo.mp4")),
        )
        db.execute(
            "INSERT INTO frames (video_id, ordinal, time_seconds, path) VALUES (%s, 0, 5, %s)",
            (video_id, str(tmp_path / "frame.jpg")),
        )

    def fail(_paths):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(worker, "embed_frames", fail)
    worker.index_visual(video_id)
    failed = client.get(f"/videos/{video_id}").json()
    assert failed["status"] == "ready"
    assert failed["visual_state"] == "failed"
    assert "model unavailable" in failed["visual_error"]

    response = client.post(f"/videos/{video_id}/retry-visual", headers={"X-Prism-Request": "1"})
    assert response.status_code == 200
    assert response.json()["visual_state"] == "pending"
    monkeypatch.setattr(
        worker, "embed_frames", lambda paths: np.array([[1.0] + [0.0] * 511], dtype=np.float32)
    )
    worker.index_visual(video_id)
    worker.index_visual(video_id)
    assert client.get(f"/videos/{video_id}").json()["visual_state"] == "ready"
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        row = db.execute(
            "SELECT count(*), count(embedding) FROM frames WHERE video_id = %s", (video_id,)
        ).fetchone()
        assert row == (1, 1)


def test_database_error_marks_visual_index_retryable(api, monkeypatch):
    from prism import worker

    client, tmp_path = api
    video_id = uuid4()
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        db.execute(
            "INSERT INTO videos (id, title, source_path, duration_seconds, status) "
            "VALUES (%s, 'Demo', %s, 10, 'ready')",
            (video_id, str(tmp_path / "demo.mp4")),
        )
    monkeypatch.setattr(worker, "embed_frames", lambda paths: [])

    def fail_register(_db):
        raise psycopg.OperationalError("connection interrupted")

    monkeypatch.setattr(worker, "register_vector", fail_register)
    worker.index_visual(video_id)
    video = client.get(f"/videos/{video_id}").json()
    assert video["visual_state"] == "failed"
    assert "database connection" in video["visual_error"]
