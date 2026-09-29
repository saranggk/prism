"""Processing behavior against the disposable PostgreSQL database and real FFmpeg."""

import os
import subprocess
from uuid import uuid4

import numpy as np
import psycopg
import pytest

from prism import worker
from prism.jobs import register_video
from prism.media import MediaError, extract_caption_srt, extract_frames, probe
from prism.transcripts import Segment, build_passages


def db():
    return psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", ""))


def register(path, duration):
    video_id = uuid4()
    register_video(video_id, "fixture", path, duration)
    return video_id


@pytest.fixture
def captioned_mp4(tmp_path, sample_mp4):
    srt = tmp_path / "captions.srt"
    srt.write_text(
        "1\n00:00:00,200 --> 00:00:00,800\nConfigure the database connection.\n",
        encoding="utf-8",
    )
    output = tmp_path / "captioned.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            str(sample_mp4),
            "-i",
            str(srt),
            "-map",
            "0:v:0",
            "-map",
            "1:s:0",
            "-c:v",
            "copy",
            "-c:s",
            "mov_text",
            "-metadata:s:s:0",
            "language=eng",
            "-y",
            str(output),
        ],
        check=True,
        timeout=20,
    )
    return output


class Tokenizer:
    def encode(self, text, add_special_tokens=True):
        return list(range(len(text.split()) + 2))


class Embedder:
    tokenizer = Tokenizer()

    def encode(self, texts, **kwargs):
        vectors = np.zeros((len(texts), 384), dtype=np.float32)
        vectors[:, 0] = 1
        return vectors


def test_silent_video_keeps_frames_and_has_no_searchable_passages(api, sample_mp4):
    client, _ = api
    video_id = register(sample_mp4, 1)
    worker.process_video(video_id)
    response = client.get(f"/videos/{video_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["transcript_state"] == "none"
    with db() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM frames WHERE video_id = %s", (video_id,)
            ).fetchone()[0]
            >= 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM passages WHERE video_id = %s", (video_id,)
            ).fetchone()[0]
            == 0
        )


def test_english_captions_become_timed_passages(api, captioned_mp4, monkeypatch):
    client, _ = api
    monkeypatch.setattr(worker, "load_embedder", Embedder)
    video_id = register(captioned_mp4, 1)
    worker.process_video(video_id)
    assert client.get(f"/videos/{video_id}").json()["transcript_state"] == "present"
    with db() as connection:
        segment = connection.execute(
            "SELECT start_seconds, end_seconds, text, source FROM transcript_segments "
            "WHERE video_id = %s",
            (video_id,),
        ).fetchone()
        passage = connection.execute(
            "SELECT start_seconds, end_seconds, vector_dims(embedding), "
            "vector_norm(embedding) FROM passages WHERE video_id = %s",
            (video_id,),
        ).fetchone()
    assert segment == (0.2, 0.8, "Configure the database connection.", "captions")
    assert passage[:3] == (0.2, 0.8, 384)
    assert passage[3] == pytest.approx(1)


def test_transcription_after_leading_silence_keeps_original_times(api, tmp_path, monkeypatch):
    client, _ = api
    video = tmp_path / "audio.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:r=25",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-t",
            "12",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-y",
            str(video),
        ],
        check=True,
        timeout=30,
    )
    monkeypatch.setattr(
        worker,
        "transcribe",
        lambda path, duration: [
            Segment(9.2, 11.4, "The database connection is configured here.", "whisper")
        ],
    )
    monkeypatch.setattr(worker, "load_embedder", Embedder)
    video_id = register(video, 12)
    worker.process_video(video_id)
    assert client.get(f"/videos/{video_id}").json()["status"] == "ready"
    with db() as connection:
        segment = connection.execute(
            "SELECT start_seconds, end_seconds, source FROM transcript_segments "
            "WHERE video_id = %s",
            (video_id,),
        ).fetchone()
        passage = connection.execute(
            "SELECT start_seconds, end_seconds FROM passages WHERE video_id = %s",
            (video_id,),
        ).fetchone()
    assert segment == (9.2, 11.4, "whisper")
    assert passage == (9.2, 11.4)


def test_restart_reuses_frames_checkpoint_without_duplicate_results(
    api, captioned_mp4, monkeypatch
):
    _, _ = api
    video_id = register(captioned_mp4, 1)
    original = worker.captions

    def crash(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(worker, "captions", crash)
    with pytest.raises(KeyboardInterrupt):
        worker.process_video(video_id)
    with db() as connection:
        frame_before = connection.execute(
            "SELECT path FROM frames WHERE video_id = %s", (video_id,)
        ).fetchall()
        assert (
            connection.execute(
                "SELECT count(*) FROM stage_checkpoints WHERE video_id = %s", (video_id,)
            ).fetchone()[0]
            == 1
        )
    monkeypatch.setattr(worker, "captions", original)
    monkeypatch.setattr(worker, "load_embedder", Embedder)
    worker.process_video(video_id)
    with db() as connection:
        assert (
            connection.execute(
                "SELECT path FROM frames WHERE video_id = %s", (video_id,)
            ).fetchall()
            == frame_before
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM passages WHERE video_id = %s", (video_id,)
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT interrupted_attempts FROM videos WHERE id = %s", (video_id,)
            ).fetchone()[0]
            == 1
        )


def test_missing_model_fails_visibly_and_retry_keeps_transcript(api, captioned_mp4, monkeypatch):
    client, _ = api
    video_id = register(captioned_mp4, 1)

    def missing():
        raise FileNotFoundError("Pinned embedding model is unavailable")

    monkeypatch.setattr(worker, "load_embedder", missing)
    worker.process_video(video_id)
    result = client.get(f"/videos/{video_id}").json()
    assert result["status"] == "failed"
    assert "unavailable" in result["error"]
    with db() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM stage_checkpoints WHERE video_id = %s", (video_id,)
            ).fetchone()[0]
            == 2
        )
        connection.execute(
            "UPDATE pgqueuer SET status = 'successful' WHERE dedupe_key = %s", (str(video_id),)
        )
    retry = client.post(f"/videos/{video_id}/retry", headers={"X-Prism-Request": "1"})
    assert retry.status_code == 200
    monkeypatch.setattr(worker, "load_embedder", Embedder)
    worker.process_video(video_id)
    with db() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM transcript_segments WHERE video_id = %s", (video_id,)
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM passages WHERE video_id = %s", (video_id,)
            ).fetchone()[0]
            == 1
        )


def test_stale_attempt_cannot_publish_frames(api, sample_mp4, monkeypatch):
    _, _ = api
    video_id = register(sample_mp4, 1)
    original = worker.extract_frames

    def replace_owner(*args):
        frames = original(*args)
        with db() as connection:
            connection.execute(
                "UPDATE videos SET attempt_token = %s WHERE id = %s", (uuid4(), video_id)
            )
        return frames

    monkeypatch.setattr(worker, "extract_frames", replace_owner)
    with pytest.raises(worker.LostOwnership):
        worker.process_video(video_id)
    with db() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM frames WHERE video_id = %s", (video_id,)
            ).fetchone()[0]
            == 0
        )


def test_terminal_queue_failure_becomes_retryable(api, sample_mp4):
    client, _ = api
    video_id = register(sample_mp4, 1)
    with db() as connection:
        connection.execute("UPDATE videos SET status = 'processing' WHERE id = %s", (video_id,))
        connection.execute(
            "UPDATE pgqueuer SET status = 'failed' WHERE dedupe_key = %s", (str(video_id),)
        )
    worker.reconcile_failed_jobs()
    assert client.get(f"/videos/{video_id}").json()["status"] == "failed"
    retry = client.post(f"/videos/{video_id}/retry", headers={"X-Prism-Request": "1"})
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "queued"


def test_three_interrupted_attempts_stop_with_retry_message(api, sample_mp4):
    client, _ = api
    video_id = register(sample_mp4, 1)
    with db() as connection:
        connection.execute(
            "UPDATE videos SET status = 'processing', interrupted_attempts = 2 WHERE id = %s",
            (video_id,),
        )
    worker.process_video(video_id)
    result = client.get(f"/videos/{video_id}").json()
    assert result["status"] == "failed"
    assert "interrupted three times" in result["error"]
    with db() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM frames WHERE video_id = %s", (video_id,)
            ).fetchone()[0]
            == 0
        )


def test_damaged_media_fails_visibly(api, tmp_path):
    client, _ = api
    video = tmp_path / "damaged.mp4"
    video.write_bytes(b"not an mp4")
    video_id = register(video, 1)
    worker.process_video(video_id)
    result = client.get(f"/videos/{video_id}").json()
    assert result["status"] == "failed"
    assert "video media" in result["error"]


def test_database_write_failure_is_visible_for_retry(api, sample_mp4, monkeypatch):
    client, _ = api
    video_id = register(sample_mp4, 1)
    original = worker._owned
    failures = 0

    def fail_once(connection, current_id, token):
        nonlocal failures
        failures += 1
        if failures == 1:
            raise psycopg.OperationalError("connection lost")
        return original(connection, current_id, token)

    monkeypatch.setattr(worker, "_owned", fail_once)
    worker.process_video(video_id)
    result = client.get(f"/videos/{video_id}").json()
    assert result["status"] == "failed"
    assert "database connection" in result["error"]


def test_ffmpeg_reads_are_local_protocol_only(sample_mp4, tmp_path, monkeypatch):
    from prism import media

    info = probe(sample_mp4)
    actual_run = media._run
    commands = []

    def track(args, timeout):
        commands.append(args)
        return actual_run(args, timeout)

    monkeypatch.setattr(media, "_run", track)
    extract_frames(sample_mp4, tmp_path / "frames", info)
    with pytest.raises(MediaError):
        extract_caption_srt(sample_mp4, 99, info.duration)
    assert all("-protocol_whitelist" in args for args in commands)
    assert all(
        args[args.index("-protocol_whitelist") + 1] in {"file", "file,pipe"} for args in commands
    )


def test_nonzero_media_start_maps_to_playback_timeline(tmp_path):
    video = tmp_path / "offset.mp4"
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
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-output_ts_offset",
            "3",
            "-y",
            str(video),
        ],
        check=True,
        timeout=20,
    )
    info = probe(video)
    assert info.start == pytest.approx(3)
    frames = extract_frames(video, tmp_path / "frames", info)
    assert frames[0][0] == pytest.approx(0)


def test_oversized_unbroken_caption_is_split_with_original_interval():
    class CharacterTokenizer:
        def encode(self, text, add_special_tokens=True):
            return list(range(len(text) + 2))

    passages = build_passages([Segment(9, 13, "x" * 420, "captions")], CharacterTokenizer())
    assert len(passages) == 3
    assert all((item.start, item.end) == (9, 13) for item in passages)
    assert all(len(item.text) + 2 <= 200 for item in passages)
