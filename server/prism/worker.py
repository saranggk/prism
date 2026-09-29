"""One-video-at-a-time, checkpointed PgQueuer processing worker."""

import argparse
import asyncio
import logging
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from pgqueuer import PgQueuer
from pgqueuer.models import Job
from pgvector.psycopg import register_vector

from prism.config import get_settings
from prism.jobs import ENTRYPOINT, connect
from prism.media import extract_frames, probe
from prism.transcripts import (
    EMBEDDING_REVISION,
    PASSAGE_VERSION,
    WHISPER_VERSION,
    build_passages,
    captions,
    download_models,
    load_embedder,
    transcribe,
)

logger = logging.getLogger(__name__)
STAGES = ("frames", "transcript", "passages")
VERSIONS = {
    "frames": "frames-pts-v1",
    "transcript": f"captions-or-{WHISPER_VERSION}",
    "passages": PASSAGE_VERSION,
}


class LostOwnership(RuntimeError):
    """Another attempt owns the video or the advisory-lock connection was lost."""


def _owned(db: psycopg.Connection, video_id: UUID, token: UUID) -> dict:
    row = db.execute(
        "SELECT source_path, duration_seconds, attempt_token, status FROM videos "
        "WHERE id = %s FOR UPDATE",
        (video_id,),
    ).fetchone()
    if row is None or row["attempt_token"] != token or row["status"] != "processing":
        raise LostOwnership(f"Processing ownership lost for {video_id}")
    return row


def _start(db: psycopg.Connection, video_id: UUID) -> UUID | None:
    with db.transaction():
        row = db.execute(
            "SELECT status, interrupted_attempts FROM videos WHERE id = %s FOR UPDATE",
            (video_id,),
        ).fetchone()
        if row is None or row["status"] in {"ready", "failed"}:
            return None
        interruptions = row["interrupted_attempts"] + int(row["status"] == "processing")
        if interruptions >= 3:
            db.execute(
                "UPDATE videos SET status = 'failed', current_step = NULL, attempt_token = NULL, "
                "error = 'Processing was interrupted three times. Retry to start again.', "
                "interrupted_attempts = %s, updated_at = now() WHERE id = %s",
                (interruptions, video_id),
            )
            return None
        token = uuid4()
        db.execute(
            "UPDATE videos SET status = 'processing', current_step = 'frames', error = NULL, "
            "attempt_token = %s, interrupted_attempts = %s, updated_at = now() WHERE id = %s",
            (token, interruptions, video_id),
        )
        return token


def _invalidate_old_versions(db: psycopg.Connection, video_id: UUID, token: UUID) -> None:
    with db.transaction():
        _owned(db, video_id, token)
        rows = db.execute(
            "SELECT stage, version FROM stage_checkpoints WHERE video_id = %s", (video_id,)
        ).fetchall()
        outdated = [
            STAGES.index(row["stage"])
            for row in rows
            if row["stage"] in STAGES and VERSIONS[row["stage"]] != row["version"]
        ]
        if not outdated:
            return
        first = min(outdated)
        for table, index in (("frames", 0), ("transcript_segments", 1), ("passages", 2)):
            if index >= first:
                db.execute(f"DELETE FROM {table} WHERE video_id = %s", (video_id,))
        db.execute(
            "DELETE FROM stage_checkpoints WHERE video_id = %s AND stage = ANY(%s)",
            (video_id, list(STAGES[first:])),
        )
        if first <= 1:
            db.execute("UPDATE videos SET transcript_state = NULL WHERE id = %s", (video_id,))


def _done(db: psycopg.Connection, video_id: UUID, stage: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM stage_checkpoints WHERE video_id = %s AND stage = %s AND version = %s",
            (video_id, stage, VERSIONS[stage]),
        ).fetchone()
        is not None
    )


def _checkpoint(db: psycopg.Connection, video_id: UUID, token: UUID, stage: str) -> None:
    db.execute(
        "INSERT INTO stage_checkpoints (video_id, stage, attempt_token, version) "
        "VALUES (%s, %s, %s, %s)",
        (video_id, stage, token, VERSIONS[stage]),
    )


def _step(db: psycopg.Connection, video_id: UUID, token: UUID, step: str) -> None:
    with db.transaction():
        _owned(db, video_id, token)
        db.execute(
            "UPDATE videos SET current_step = %s, updated_at = now() WHERE id = %s",
            (step, video_id),
        )


def process_video(video_id: UUID) -> None:
    """Process one persisted upload. A dedicated DB session owns its advisory lock."""
    with connect() as db:
        locked = db.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS locked", (str(video_id),)
        ).fetchone()["locked"]
        if not locked:
            raise LostOwnership(f"Video {video_id} is already processing")
        token = None
        try:
            token = _start(db, video_id)
            if token is None:
                return
            _invalidate_old_versions(db, video_id, token)
            row = _owned_read(db, video_id, token)
            source = Path(row["source_path"])
            info = probe(source)
            if not _done(db, video_id, "frames"):
                frame_dir = get_settings().storage_path / "frames" / str(video_id) / str(token)
                frames = extract_frames(source, frame_dir, info)
                with db.transaction():
                    _owned(db, video_id, token)
                    with db.cursor() as cursor:
                        cursor.executemany(
                            "INSERT INTO frames (video_id, ordinal, time_seconds, path) "
                            "VALUES (%s, %s, %s, %s)",
                            [
                                (video_id, ordinal, time, str(path))
                                for ordinal, (time, path) in enumerate(frames)
                            ],
                        )
                    _checkpoint(db, video_id, token, "frames")
            _step(db, video_id, token, "transcript")
            if not _done(db, video_id, "transcript"):
                segments = captions(source, info)
                if not segments and info.has_audio:
                    segments = transcribe(source, info.duration)
                with db.transaction():
                    _owned(db, video_id, token)
                    if segments:
                        with db.cursor() as cursor:
                            cursor.executemany(
                                "INSERT INTO transcript_segments "
                                "(video_id, ordinal, start_seconds, end_seconds, text, source) "
                                "VALUES (%s, %s, %s, %s, %s, %s)",
                                [
                                    (
                                        video_id,
                                        ordinal,
                                        item.start,
                                        item.end,
                                        item.text,
                                        item.source,
                                    )
                                    for ordinal, item in enumerate(segments)
                                ],
                            )
                    db.execute(
                        "UPDATE videos SET transcript_state = %s WHERE id = %s",
                        ("present" if segments else "none", video_id),
                    )
                    _checkpoint(db, video_id, token, "transcript")
            _step(db, video_id, token, "passages")
            if not _done(db, video_id, "passages"):
                rows = db.execute(
                    "SELECT ordinal, start_seconds, end_seconds, text, source "
                    "FROM transcript_segments WHERE video_id = %s ORDER BY ordinal",
                    (video_id,),
                ).fetchall()
                if rows:
                    from prism.transcripts import Segment

                    segments = [
                        Segment(
                            row["start_seconds"], row["end_seconds"], row["text"], row["source"]
                        )
                        for row in rows
                    ]
                    model = load_embedder()
                    passages = build_passages(segments, model.tokenizer)
                    vectors = model.encode(
                        [item.text for item in passages],
                        normalize_embeddings=True,
                        convert_to_numpy=True,
                    )
                else:
                    passages, vectors = [], []
                with db.transaction():
                    _owned(db, video_id, token)
                    register_vector(db)
                    if passages:
                        with db.cursor() as cursor:
                            cursor.executemany(
                                "INSERT INTO passages (video_id, ordinal, start_seconds, "
                                "end_seconds, text, segment_start_ordinal, segment_end_ordinal, "
                                "embedding, model_revision) VALUES (%s, %s, %s, %s, %s, %s, "
                                "%s, %s, %s)",
                                [
                                    (
                                        video_id,
                                        ordinal,
                                        item.start,
                                        item.end,
                                        item.text,
                                        item.first_segment,
                                        item.last_segment,
                                        vector,
                                        EMBEDDING_REVISION,
                                    )
                                    for ordinal, (item, vector) in enumerate(
                                        zip(passages, vectors, strict=True)
                                    )
                                ],
                            )
                    _checkpoint(db, video_id, token, "passages")
            with db.transaction():
                _owned(db, video_id, token)
                db.execute(
                    "UPDATE videos SET status = 'ready', current_step = NULL, error = NULL, "
                    "attempt_token = NULL, updated_at = now() WHERE id = %s",
                    (video_id,),
                )
        except LostOwnership:
            raise
        except psycopg.Error:
            logger.exception("Database connection failed while processing video %s", video_id)
            if token is None:
                raise
            # The lock connection may be gone. A fresh session can publish a
            # failure only if this attempt still owns the video.
            with connect() as recovery, recovery.transaction():
                recovery.execute(
                    "UPDATE videos SET status = 'failed', current_step = NULL, "
                    "attempt_token = NULL, error = 'Processing lost its database connection. "
                    "Retry to resume.', updated_at = now() "
                    "WHERE id = %s AND attempt_token = %s AND status = 'processing'",
                    (video_id, token),
                )
        except Exception as exc:
            logger.exception("Processing failed for video %s", video_id)
            if token is not None:
                with db.transaction():
                    _owned(db, video_id, token)
                    db.execute(
                        "UPDATE videos SET status = 'failed', current_step = NULL, "
                        "attempt_token = NULL, error = %s, updated_at = now() WHERE id = %s",
                        (f"Processing failed: {str(exc)[:400]}", video_id),
                    )
        finally:
            # Closing this dedicated connection also releases the session lock.
            if not db.closed:
                try:
                    db.execute(
                        "SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (str(video_id),)
                    )
                except psycopg.Error:
                    pass  # Closing a broken session releases its lock.


def _owned_read(db: psycopg.Connection, video_id: UUID, token: UUID) -> dict:
    with db.transaction():
        return _owned(db, video_id, token)


def reconcile_failed_jobs() -> None:
    """Expose terminal queue failures for manual retry after a worker restart."""
    with connect() as db, db.transaction():
        db.execute(
            "UPDATE videos AS v SET status = 'failed', current_step = NULL, "
            "attempt_token = NULL, error = 'Processing stopped unexpectedly. Retry to resume.', "
            "updated_at = now() FROM pgqueuer AS q "
            "WHERE v.job_id = q.id AND v.status = 'processing' "
            "AND q.status IN ('failed', 'exception')"
        )


async def run_worker() -> None:
    await asyncio.to_thread(reconcile_failed_jobs)
    url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as connection:
        queue = PgQueuer.from_psycopg_connection(connection)

        @queue.entrypoint(ENTRYPOINT, concurrency_limit=1, on_failure="hold")
        async def handle(job: Job) -> None:
            if job.payload is None:
                raise ValueError("Video job has no ID")
            await asyncio.to_thread(process_video, UUID(job.payload.decode("utf-8")))

        # PgQueuer reserves capacity for heartbeats; the entrypoint limit keeps
        # actual video processing at one job at a time.
        await queue.run(batch_size=1, max_concurrent_tasks=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prism video processing worker")
    parser.add_argument(
        "--download-models",
        action="store_true",
        help="Download and verify pinned local models before processing",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.download_models:
        download_models()
        load_embedder()
        print("Pinned transcription and embedding models are ready.")
    else:
        try:
            asyncio.run(run_worker())
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
