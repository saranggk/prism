import io

import psycopg
import pytest


def headers():
    return {"X-Prism-Request": "1", "Origin": "http://127.0.0.1:3000"}


def test_upload_rejects_unsupported_and_does_not_queue(api):
    client, _ = api
    response = client.post(
        "/videos",
        files={"file": ("bad.mp4", io.BytesIO(b"not an mp4"), "video/mp4")},
        headers=headers(),
    )
    assert response.status_code == 422
    assert "MP4" in response.json()["detail"]
    assert client.get("/videos").json() == []


def test_upload_requires_local_origin_and_custom_header(api):
    client, _ = api
    assert client.post("/videos", headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.post("/videos", headers={"Origin": "http://127.0.0.1:3000"}).status_code == 403


@pytest.mark.parametrize("claimed_length", [None, "1"])
def test_total_request_limit_with_missing_or_false_content_length(api, monkeypatch, claimed_length):
    client, _ = api
    monkeypatch.setattr("prism.uploads.MAX_REQUEST_BYTES", 2 * 1024 * 1024)

    def giant_body():
        yield (
            b'--x\r\nContent-Disposition: form-data; name="file"; filename="giant.mp4"\r\n'
            b"Content-Type: video/mp4\r\n\r\n"
        )
        for _ in range(3):
            yield b"x" * (1024 * 1024)
        yield b"\r\n--x--\r\n"

    request_headers = {**headers(), "Content-Type": "multipart/form-data; boundary=x"}
    if claimed_length is not None:
        request_headers["Content-Length"] = claimed_length
    response = client.post("/videos", content=giant_body(), headers=request_headers)
    assert response.status_code == 413
    assert client.get("/videos").json() == []


def test_interrupted_transfer_does_not_register_video(api):
    client, root = api

    def interrupted_body():
        yield b'--x\r\nContent-Disposition: form-data; name="file"; filename="broken.mp4"\r\n\r\n'
        yield b"unfinished"
        raise ConnectionError("client disconnected")

    with pytest.raises(ConnectionError, match="client disconnected"):
        client.post(
            "/videos",
            content=interrupted_body(),
            headers={**headers(), "Content-Type": "multipart/form-data; boundary=x"},
        )
    assert client.get("/videos").json() == []
    assert not (root / "uploads").exists()


def test_queue_failure_rolls_back_video_and_file(api, sample_mp4, monkeypatch):
    client, root = api

    def fail_enqueue(*args, **kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr("prism.jobs.SyncQueries.enqueue", fail_enqueue)
    with sample_mp4.open("rb") as file, pytest.raises(RuntimeError, match="queue unavailable"):
        client.post("/videos", files={"file": ("sample.mp4", file, "video/mp4")}, headers=headers())
    assert client.get("/videos").json() == []
    assert list((root / "uploads").iterdir()) == []


@pytest.mark.parametrize("name", ["sample.mov", "sample.mp4"])
def test_valid_media_registration(api, name, sample_mp4):
    client, root = api
    with sample_mp4.open("rb") as file:
        response = client.post(
            "/videos", files={"file": (name, file, "video/mp4")}, headers=headers()
        )
    if name.endswith(".mov"):
        assert response.status_code == 422
        return
    assert response.status_code == 201, response.text
    video = response.json()
    assert video["status"] == "queued"
    assert video["duration_seconds"] > 0
    assert (root / "uploads" / video["id"] / "source.mp4").exists()
    assert client.get(f"/videos/{video['id']}").json()["id"] == video["id"]
    assert any(item["id"] == video["id"] for item in client.get("/videos").json())
    with psycopg.connect(
        __import__("os").environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")
    ) as db:
        row = db.execute(
            "SELECT count(*) FROM pgqueuer WHERE dedupe_key = %s", (video["id"],)
        ).fetchone()
        assert row == (1,)
