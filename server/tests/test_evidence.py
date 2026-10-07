"""Evidence inspection reads source records without changing search results."""

import os
from uuid import uuid4

import psycopg


def test_inspection_scopes_segments_frames_and_media_to_one_video(api):
    client, tmp_path = api
    video_id, other_id = uuid4(), uuid4()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"media")
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        for identifier, path in ((video_id, source), (other_id, tmp_path / "missing.mp4")):
            db.execute(
                "INSERT INTO videos (id, title, source_path, duration_seconds, status, "
                "transcript_state, visual_state) VALUES (%s, 'Source', %s, 60, 'ready', "
                "'present', 'ready')",
                (identifier, str(path)),
            )
            db.execute(
                "INSERT INTO transcript_segments (video_id, ordinal, start_seconds, "
                "end_seconds, text, source) VALUES (%s, 0, 18, 22, 'Source words', 'captions')",
                (identifier,),
            )
            db.execute(
                "INSERT INTO frames (video_id, ordinal, time_seconds, path) "
                "VALUES (%s, 0, 20, %s)",
                (identifier, str(frame) if identifier == video_id else str(tmp_path / "lost.jpg")),
            )
    response = client.get(f"/videos/{video_id}/evidence?time_seconds=20")
    assert response.status_code == 200
    body = response.json()
    assert body["video_id"] == str(video_id)
    assert body["window_start_seconds"] == 5
    assert body["window_end_seconds"] == 35
    assert body["media_available"] is True
    assert [
        (row["start_seconds"], row["end_seconds"], row["text"])
        for row in body["segments"]
    ] == [(18, 22, "Source words")]
    assert [
        (row["ordinal"], row["time_seconds"], row["media_available"])
        for row in body["frames"]
    ] == [(0, 20, True)]
    assert body["frames"][0]["url"] == f"/videos/{video_id}/frames/0"
    missing = client.get(f"/videos/{other_id}/evidence?time_seconds=20").json()
    assert missing["media_available"] is False
    assert missing["frames"][0]["media_available"] is False


def test_inspection_bounds_time_and_reports_missing_evidence(api):
    client, tmp_path = api
    video_id = uuid4()
    frame = tmp_path / "silent-frame.jpg"
    frame.write_bytes(b"frame")
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        db.execute(
            "INSERT INTO videos (id, title, source_path, duration_seconds, status, "
            "transcript_state, visual_state) VALUES (%s, 'Silent', %s, 12, 'ready', "
            "'none', 'ready')",
            (video_id, str(tmp_path / "missing.mp4")),
        )
        db.execute(
            "INSERT INTO frames (video_id, ordinal, time_seconds, path) "
            "VALUES (%s, 0, 5, %s)",
            (video_id, str(frame)),
        )
    body = client.get(f"/videos/{video_id}/evidence?time_seconds=0").json()
    assert body["transcript_state"] == "none"
    assert body["segments"] == []
    assert body["frames"][0]["time_seconds"] == 5
    assert body["frames"][0]["media_available"] is True
    assert body["window_start_seconds"] == 0
    assert body["window_end_seconds"] == 12
    for time in ("-1", "12.1", "NaN", "Infinity"):
        assert client.get(f"/videos/{video_id}/evidence?time_seconds={time}").status_code == 422
    assert client.get(f"/videos/{uuid4()}/evidence?time_seconds=2").status_code == 404
