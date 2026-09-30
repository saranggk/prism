"""Serve registered video and frame files by database ID."""

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse

from prism.config import get_settings
from prism.jobs import connect

router = APIRouter()


def _registered_file(value: str) -> Path:
    root = get_settings().storage_path.resolve()
    path = Path(value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Media file is unavailable.")
    return path


@router.get("/videos/{video_id}/media", response_class=FileResponse)
def video_media(video_id: UUID) -> FileResponse:
    with connect() as db:
        row = db.execute("SELECT source_path FROM videos WHERE id = %s", (video_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found.")
    return FileResponse(_registered_file(row["source_path"]), media_type="video/mp4")


@router.get("/videos/{video_id}/frames/{ordinal}", response_class=FileResponse)
def video_frame(video_id: UUID, ordinal: int) -> FileResponse:
    with connect() as db:
        row = db.execute(
            "SELECT path FROM frames WHERE video_id = %s AND ordinal = %s", (video_id, ordinal)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Frame not found.")
    return FileResponse(_registered_file(row["path"]), media_type="image/jpeg")
