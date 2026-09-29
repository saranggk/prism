import os

import psycopg
from test_uploads import headers


def test_retry_failed_video_only_queues_once(api, sample_mp4):
    client, _ = api
    with sample_mp4.open("rb") as file:
        uploaded = client.post(
            "/videos", files={"file": ("sample.mp4", file, "video/mp4")}, headers=headers()
        )
    assert uploaded.status_code == 201, uploaded.text
    video_id = uploaded.json()["id"]
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        db.execute(
            "UPDATE videos SET status = 'failed', error = 'transcription failed' WHERE id = %s",
            (video_id,),
        )
        db.execute("UPDATE pgqueuer SET status = 'successful' WHERE dedupe_key = %s", (video_id,))
    first = client.post(f"/videos/{video_id}/retry", headers=headers())
    second = client.post(f"/videos/{video_id}/retry", headers=headers())
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "queued"
    assert second.status_code == 409
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        rows = db.execute(
            "SELECT count(*) FROM pgqueuer WHERE dedupe_key = %s "
            "AND status IN ('queued', 'picked')",
            (video_id,),
        ).fetchone()
        assert rows == (1,)
