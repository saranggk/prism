"""Atomic video and PgQueuer registration, plus library state reads."""

from pathlib import Path
from uuid import UUID

import psycopg
from fastapi import HTTPException
from pgqueuer.db import SyncPsycopgDriver
from pgqueuer.queries import SyncQueries
from psycopg.rows import dict_row

from prism.config import get_settings
from prism.models import Video

ENTRYPOINT = "process_video"
VIDEO_COLUMNS = "id, title, duration_seconds, status, current_step, error, created_at, updated_at"


def connect() -> psycopg.Connection:
    url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return psycopg.connect(url, autocommit=True, row_factory=dict_row, connect_timeout=3)


def register_video(video_id: UUID, title: str, source_path: Path, duration: float) -> Video:
    with connect() as db, db.transaction():
        db.execute(
            "INSERT INTO videos (id, title, source_path, duration_seconds, status) "
            "VALUES (%s, %s, %s, %s, 'queued')",
            (video_id, title, str(source_path), duration),
        )
        (job_id,) = SyncQueries(SyncPsycopgDriver(db)).enqueue(
            ENTRYPOINT, str(video_id).encode(), dedupe_key=str(video_id)
        )
        db.execute("UPDATE videos SET job_id = %s WHERE id = %s", (job_id, video_id))
        row = db.execute(
            f"SELECT {VIDEO_COLUMNS} FROM videos WHERE id = %s", (video_id,)
        ).fetchone()
    return Video.model_validate(row)


def list_videos() -> list[Video]:
    with connect() as db:
        rows = db.execute(
            f"SELECT {VIDEO_COLUMNS} FROM videos ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [Video.model_validate(row) for row in rows]


def get_video(video_id: UUID) -> Video:
    with connect() as db:
        row = db.execute(
            f"SELECT {VIDEO_COLUMNS} FROM videos WHERE id = %s", (video_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found.")
    return Video.model_validate(row)


def retry_video(video_id: UUID) -> Video:
    with connect() as db, db.transaction():
        row = db.execute(
            "SELECT status FROM videos WHERE id = %s FOR UPDATE", (video_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Video not found.")
        if row["status"] != "failed":
            raise HTTPException(status_code=409, detail="Only failed videos can be retried.")
        (job_id,) = SyncQueries(SyncPsycopgDriver(db)).enqueue(
            ENTRYPOINT, str(video_id).encode(), dedupe_key=str(video_id), on_conflict="skip"
        )
        if job_id is None:
            raise HTTPException(status_code=409, detail="A job for this video is already active.")
        db.execute(
            "UPDATE videos SET status = 'queued', current_step = NULL, error = NULL, "
            "job_id = %s, updated_at = now() WHERE id = %s",
            (job_id, video_id),
        )
        result = db.execute(
            f"SELECT {VIDEO_COLUMNS} FROM videos WHERE id = %s", (video_id,)
        ).fetchone()
    return Video.model_validate(result)


def referenced_upload_ids() -> set[str]:
    with connect() as db:
        return {str(row["id"]) for row in db.execute("SELECT id FROM videos")}
