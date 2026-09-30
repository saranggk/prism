"""ID-only playback and frame reads through the HTTP boundary."""

import os
from uuid import uuid4

import psycopg


def test_video_ranges_and_frame_reads(api, sample_mp4):
    client, data_dir = api
    video_id = uuid4()
    source = data_dir / "uploads" / str(video_id) / "source.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(sample_mp4.read_bytes())
    frame = data_dir / "frames" / str(video_id) / "0.jpg"
    frame.parent.mkdir(parents=True)
    frame.write_bytes(b"\xff\xd8\xff\xd9")
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        db.execute(
            "INSERT INTO videos (id, title, source_path, duration_seconds, status) "
            "VALUES (%s, 'fixture', %s, 1, 'ready')",
            (video_id, str(source)),
        )
        db.execute(
            "INSERT INTO frames (video_id, ordinal, time_seconds, path) VALUES (%s, 0, 0, %s)",
            (video_id, str(frame)),
        )
    media = client.get(f"/videos/{video_id}/media", headers={"Range": "bytes=0-15"})
    assert media.status_code == 206
    assert media.content == source.read_bytes()[:16]
    assert media.headers["content-range"].startswith("bytes 0-15/")
    assert (
        client.get(f"/videos/{video_id}/media", headers={"Range": "bytes=999999-"}).status_code
        == 416
    )
    preview = client.get(f"/videos/{video_id}/frames/0")
    assert preview.status_code == 200
    assert preview.content == frame.read_bytes()
    assert preview.headers["content-type"].startswith("image/jpeg")
    assert client.get(f"/videos/{video_id}/frames/1").status_code == 404
    source.unlink()
    assert client.get(f"/videos/{video_id}/media").status_code == 404


def test_playback_rejects_paths_outside_storage(api, sample_mp4):
    client, _ = api
    video_id = uuid4()
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        db.execute(
            "INSERT INTO videos (id, title, source_path, duration_seconds, status) "
            "VALUES (%s, 'fixture', %s, 1, 'ready')",
            (video_id, str(sample_mp4)),
        )
    assert client.get(f"/videos/{video_id}/media").status_code == 404
