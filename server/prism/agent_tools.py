"""Read-only, video-scoped evidence tools for a future research agent."""

from typing import Literal, NamedTuple
from uuid import UUID

from pydantic import BaseModel

from prism.evidence import EvidenceFrame, EvidenceSegment, EvidenceWindow, inspect_evidence
from prism.jobs import connect
from prism.search import SearchResult, search

SearchMode = Literal["combined", "transcript", "visual"]


class SourceRef(BaseModel):
    video_id: UUID
    kind: Literal["segment", "frame"]
    ordinal: int


class InspectedSegment(EvidenceSegment):
    ref: SourceRef


class InspectedFrame(EvidenceFrame):
    ref: SourceRef


class MomentInspection(EvidenceWindow):
    segments: list[InspectedSegment]
    frames: list[InspectedFrame]


class MomentSearch(BaseModel):
    state: Literal["results", "no_searchable_videos", "no_matches"]
    moments: list[SearchResult]
    unsearchable_video_ids: list[UUID]


class ReadyScope(NamedTuple):
    video_ids: list[UUID]
    transcript_ids: set[UUID]
    visual_ids: set[UUID]


def _ready_scope(video_ids: list[UUID]) -> ReadyScope:
    selected = list(dict.fromkeys(video_ids))
    if not selected:
        raise ValueError("Select at least one video for research.")
    with connect() as db:
        rows = db.execute(
            "SELECT id, transcript_state, visual_state FROM videos "
            "WHERE status = 'ready' AND id = ANY(%s)",
            (selected,),
        ).fetchall()
    if len(rows) != len(selected):
        raise ValueError("A selected video was not found or is not ready.")
    return ReadyScope(
        selected,
        {row["id"] for row in rows if row["transcript_state"] == "present"},
        {row["id"] for row in rows if row["visual_state"] == "ready"},
    )


def search_moments(
    query: str, video_ids: list[UUID], mode: SearchMode = "combined"
) -> MomentSearch:
    """Find timestamped candidates; title matches are excluded from evidence."""
    scope = _ready_scope(video_ids)
    if mode not in ("combined", "transcript", "visual"):
        raise ValueError("Choose a supported search mode.")
    if not query.strip() or len(query) > 1000:
        raise ValueError("Enter a search question of at most 1000 characters.")
    response = search(q=query, video_ids=scope.video_ids, mode=mode)
    if mode == "transcript":
        searchable = scope.transcript_ids
    elif mode == "visual":
        searchable = scope.visual_ids
    else:
        searchable = scope.transcript_ids | scope.visual_ids
    unsearchable = [video_id for video_id in scope.video_ids if video_id not in searchable]
    state = response.state
    if state == "results" and not response.results:
        state = "no_matches" if searchable else "no_searchable_videos"
    return MomentSearch(state=state, moments=response.results, unsearchable_video_ids=unsearchable)


def inspect_moment(video_id: UUID, time_seconds: float, video_ids: list[UUID]) -> MomentInspection:
    """Inspect exact source rows around one time within the selected videos."""
    scope = _ready_scope(video_ids)
    if video_id not in scope.video_ids:
        raise ValueError("Video is outside the selected videos.")
    window = inspect_evidence(video_id=video_id, time_seconds=time_seconds)
    return MomentInspection(
        **window.model_dump(exclude={"segments", "frames"}),
        segments=[
            InspectedSegment(
                **segment.model_dump(),
                ref=SourceRef(video_id=video_id, kind="segment", ordinal=segment.ordinal),
            )
            for segment in window.segments
        ],
        frames=[
            InspectedFrame(
                **frame.model_dump(),
                ref=SourceRef(video_id=video_id, kind="frame", ordinal=frame.ordinal),
            )
            for frame in window.frames
        ],
    )
