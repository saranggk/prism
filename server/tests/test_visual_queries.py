"""Image queries through the HTTP boundary and real pgvector ranking."""

import io
import os
import subprocess
from uuid import uuid4

import numpy as np
import psycopg
from PIL import Image

from prism.visual import MODEL_REVISION


class ImageModel:
    def encode(self, images, **kwargs):
        vector = np.zeros(512, dtype=np.float32)
        vector[0] = 1
        return np.array([vector for _ in images])


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (16, 16), "blue").save(output, format="PNG")
    return output.getvalue()


def seed(tmp_path, *, ready=True, indexed=True):
    video_id = uuid4()
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        db.execute(
            "INSERT INTO videos (id, title, source_path, duration_seconds, status, visual_state) "
            "VALUES (%s, %s, %s, 30, %s, %s)",
            (
                video_id,
                f"Video {video_id}",
                str(tmp_path / f"{video_id}.mp4"),
                "ready" if ready else "processing",
                "ready" if indexed else "pending",
            ),
        )
        if indexed:
            for ordinal, seconds in enumerate((4.0, 7.0, 15.0)):
                vector = "[1," + "0," * 510 + "0]"
                db.execute(
                    "INSERT INTO frames (video_id, ordinal, time_seconds, path, "
                    "embedding, model_revision) "
                    "VALUES (%s, %s, %s, %s, %s::vector, %s)",
                    (
                        video_id,
                        ordinal,
                        seconds,
                        str(tmp_path / f"{ordinal}.jpg"),
                        vector,
                        MODEL_REVISION,
                    ),
                )
    return video_id


def test_image_query_filters_and_collapses_nearby_frames(api, monkeypatch):
    from prism import visual_queries

    client, tmp_path = api
    monkeypatch.setattr(visual_queries, "load_visual_model", ImageModel)
    first = seed(tmp_path)
    second = seed(tmp_path)
    seed(tmp_path, ready=False)
    pending = seed(tmp_path, indexed=False)
    response = client.post(
        "/search/visual",
        params=[("video_ids", str(first)), ("video_ids", str(pending))],
        files={"file": ("query.png", image_bytes(), "image/png")},
        headers={"X-Prism-Request": "1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "results"
    assert [result["frame_time_seconds"] for result in body["results"]] == [4, 15]
    assert all(result["video_id"] == str(first) for result in body["results"])
    assert all(result["query_time_seconds"] == 0 for result in body["results"])
    assert body["results"][0]["frame_url"] == f"/videos/{first}/frames/0"
    assert body["skipped_videos"] == [f"Video {pending}"]
    assert str(second) not in str(body)


def test_dense_scene_does_not_hide_another_video(api, monkeypatch):
    from prism import visual_queries

    client, tmp_path = api
    monkeypatch.setattr(visual_queries, "load_visual_model", ImageModel)
    first = seed(tmp_path)
    second = seed(tmp_path)
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        for ordinal in range(3, 33):
            db.execute(
                "INSERT INTO frames (video_id, ordinal, time_seconds, path, embedding, "
                "model_revision) VALUES (%s, %s, %s, %s, %s::vector, %s)",
                (
                    first,
                    ordinal,
                    4 + ordinal / 100,
                    str(tmp_path / f"dense-{ordinal}.jpg"),
                    "[1," + "0," * 510 + "0]",
                    MODEL_REVISION,
                ),
            )
    response = client.post(
        "/search/visual",
        files={"file": ("query.png", image_bytes(), "image/png")},
        headers={"X-Prism-Request": "1"},
    )
    assert response.status_code == 200
    assert {item["video_id"] for item in response.json()["results"]} == {str(first), str(second)}


def test_image_query_validation_and_empty_states(api, monkeypatch):
    from prism import visual_queries

    client, tmp_path = api
    monkeypatch.setattr(visual_queries, "load_visual_model", ImageModel)
    pending = seed(tmp_path, indexed=False)
    response = client.post(
        "/search/visual",
        files={"file": ("query.png", image_bytes(), "image/png")},
        headers={"X-Prism-Request": "1"},
    )
    assert response.json()["state"] == "no_searchable_videos"
    assert response.json()["skipped_videos"] == [f"Video {pending}"]
    invalid_before_indexing = client.post(
        "/search/visual",
        files={"file": ("bad.png", b"bad")},
        headers={"X-Prism-Request": "1"},
    )
    assert invalid_before_indexing.status_code == 422
    seed(tmp_path)
    for name, content in (("query.txt", b"bad"), ("query.png", b"bad"), ("query.png", b"")):
        response = client.post(
            "/search/visual",
            files={"file": (name, content)},
            headers={"X-Prism-Request": "1"},
        )
        assert response.status_code == 422
    assert (
        client.post(
            "/search/visual",
            params={"video_ids": str(uuid4())},
            files={"file": ("query.png", image_bytes(), "image/png")},
            headers={"X-Prism-Request": "1"},
        ).status_code
        == 422
    )


def test_clip_query_reports_sample_time_and_rejects_bad_clip(api, sample_mp4, monkeypatch):
    from prism import visual_queries

    client, tmp_path = api
    monkeypatch.setattr(visual_queries, "load_visual_model", ImageModel)
    video_id = seed(tmp_path)
    response = client.post(
        "/search/visual",
        files={"file": ("sample.mp4", sample_mp4.read_bytes(), "video/mp4")},
        headers={"X-Prism-Request": "1"},
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["video_id"] == str(video_id)
    assert response.json()["results"][0]["query_time_seconds"] == 0
    invalid = client.post(
        "/search/visual",
        files={"file": ("bad.mp4", b"not a video", "video/mp4")},
        headers={"X-Prism-Request": "1"},
    )
    assert invalid.status_code == 422


def test_later_clip_sample_can_support_match(api, tmp_path, monkeypatch):
    from prism import visual_queries

    class ColorModel:
        def encode(self, images, **kwargs):
            vectors = []
            for image in images:
                red, _, blue = image.getpixel((image.width // 2, image.height // 2))
                vector = np.zeros(512, dtype=np.float32)
                vector[0 if blue > red else 1] = 1
                vectors.append(vector)
            return np.array(vectors)

    client, storage = api
    monkeypatch.setattr(visual_queries, "load_visual_model", ColorModel)
    video_id = seed(storage)
    clip = tmp_path / "two-views.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=64x64:r=10:d=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:r=10:d=2",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(clip),
        ],
        check=True,
        timeout=20,
    )
    response = client.post(
        "/search/visual",
        files={"file": ("two-views.mp4", clip.read_bytes(), "video/mp4")},
        headers={"X-Prism-Request": "1"},
    )
    assert response.status_code == 200
    first = response.json()["results"][0]
    assert first["video_id"] == str(video_id)
    assert first["query_time_seconds"] == 2
    assert first["frame_time_seconds"] == 4


def test_visual_request_limit_applies_before_multipart_parsing(api, monkeypatch):
    from prism import uploads

    client, _ = api
    monkeypatch.setattr(uploads, "MAX_VISUAL_REQUEST_BYTES", 100)
    response = client.post(
        "/search/visual",
        files={"file": ("query.png", image_bytes(), "image/png")},
        headers={"X-Prism-Request": "1", "Content-Length": "1"},
    )
    assert response.status_code == 413
    assert response.json()["detail"] == "Query upload exceeds the 60 MiB file limit."
