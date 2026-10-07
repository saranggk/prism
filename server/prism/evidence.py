"""Inspect existing transcript segments and sampled frames around a source time."""

import math
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from prism.jobs import connect
from prism.playback import _registered_file

router = APIRouter()
WINDOW_RADIUS_SECONDS = 15


class EvidenceSegment(BaseModel):
    ordinal: int
    start_seconds: float
    end_seconds: float
    text: str
    source: Literal["captions", "whisper"]


class EvidenceFrame(BaseModel):
    ordinal: int
    time_seconds: float
    url: str
    media_available: bool


class EvidenceWindow(BaseModel):
    video_id: UUID
    video_title: str
    duration_seconds: float
    selected_time_seconds: float
    window_start_seconds: float
    window_end_seconds: float
    transcript_state: Literal["present", "none"] | None
    visual_state: Literal["pending", "indexing", "ready", "failed"] | None
    media_available: bool
    playback_url: str
    segments: list[EvidenceSegment]
    frames: list[EvidenceFrame]


def _available(path: str) -> bool:
    try:
        _registered_file(path)
        return True
    except HTTPException:
        return False


@router.get("/videos/{video_id}/evidence", response_model=EvidenceWindow)
def inspect_evidence(
    video_id: UUID,
    time_seconds: Annotated[float, Query()],
) -> EvidenceWindow:
    with connect() as db:
        video = db.execute(
            "SELECT id, title, duration_seconds, status, transcript_state, "
            "visual_state, source_path FROM videos WHERE id = %s",
            (video_id,),
        ).fetchone()
        if video is None:
            raise HTTPException(status_code=404, detail="Video not found.")
        if video["status"] != "ready":
            raise HTTPException(status_code=422, detail="Video is not ready for inspection.")
        if not math.isfinite(time_seconds) or not 0 <= time_seconds <= video["duration_seconds"]:
            raise HTTPException(status_code=422, detail="Choose a time inside the source video.")
        start = max(0, time_seconds - WINDOW_RADIUS_SECONDS)
        end = min(video["duration_seconds"], time_seconds + WINDOW_RADIUS_SECONDS)
        segments = db.execute(
            "SELECT ordinal, start_seconds, end_seconds, text, source "
            "FROM transcript_segments WHERE video_id = %s "
            "AND start_seconds <= %s AND end_seconds >= %s "
            "ORDER BY start_seconds, ordinal LIMIT 100",
            (video_id, end, start),
        ).fetchall()
        frames = db.execute(
            "SELECT ordinal, time_seconds, path FROM frames "
            "WHERE video_id = %s AND time_seconds BETWEEN %s AND %s "
            "ORDER BY time_seconds, ordinal LIMIT 30",
            (video_id, start, end),
        ).fetchall()
    return EvidenceWindow(
        video_id=video_id,
        video_title=video["title"],
        duration_seconds=video["duration_seconds"],
        selected_time_seconds=time_seconds,
        window_start_seconds=start,
        window_end_seconds=end,
        transcript_state=video["transcript_state"],
        visual_state=video["visual_state"],
        media_available=_available(video["source_path"]),
        playback_url=f"/videos/{video_id}/media",
        segments=[EvidenceSegment(**row) for row in segments],
        frames=[
            EvidenceFrame(
                ordinal=row["ordinal"],
                time_seconds=row["time_seconds"],
                url=f"/videos/{video_id}/frames/{row['ordinal']}",
                media_available=_available(row["path"]),
            )
            for row in frames
        ],
    )
