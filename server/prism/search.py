"""Filtered transcript, frame, and title retrieval with explicit evidence."""

import math
import re
import threading
from functools import lru_cache
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pgvector.psycopg import register_vector
from pydantic import BaseModel

from prism.config import get_settings
from prism.jobs import connect
from prism.transcripts import load_embedder
from prism.visual import MODEL_REVISION as VISUAL_REVISION
from prism.visual import embed_query

router = APIRouter()
_text_lock = threading.Lock()
_visual_lock = threading.Lock()
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "do",
    "does",
    "for",
    "how",
    "in",
    "is",
    "of",
    "on",
    "the",
    "they",
    "to",
    "what",
    "when",
    "where",
    "which",
    "why",
    "with",
}


@lru_cache(maxsize=1)
def _model():
    return load_embedder()


class SearchResult(BaseModel):
    video_id: UUID
    video_title: str
    start_seconds: float
    end_seconds: float
    excerpt: str | None
    evidence: list[Literal["transcript", "frame"]]
    preview_time_seconds: float | None
    preview_url: str | None
    playback_url: str


class VideoResult(BaseModel):
    video_id: UUID
    video_title: str
    playback_url: str
    evidence: Literal["title"] = "title"


class SearchResponse(BaseModel):
    state: Literal["results", "no_searchable_videos", "no_matches"]
    results: list[SearchResult]
    video_results: list[VideoResult] = []
    provisional: bool = True


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower())) - STOPWORDS


def _title_matches(words: set[str], title: str) -> bool:
    return bool(words) and len(words & _tokens(title)) >= min(2, len(words))


def _candidate(row: dict, *, frame: bool) -> SearchResult:
    video_id = row["video_id"]
    frame_ordinal = row["frame_ordinal"]
    time = row["preview_time_seconds"]
    return SearchResult(
        video_id=video_id,
        video_title=row["video_title"],
        start_seconds=max(0, time - 2.5) if frame else row["start_seconds"],
        end_seconds=min(row["duration_seconds"], time + 2.5) if frame else row["end_seconds"],
        excerpt=None if frame else row["excerpt"],
        evidence=["frame"] if frame else ["transcript"],
        preview_time_seconds=time,
        preview_url=f"/videos/{video_id}/frames/{frame_ordinal}"
        if frame_ordinal is not None
        else None,
        playback_url=f"/videos/{video_id}/media",
    )


@router.get("/search", response_model=SearchResponse)
def search(
    q: Annotated[str, Query(min_length=1, max_length=1000)],
    video_ids: Annotated[list[UUID] | None, Query()] = None,
    mode: Literal["combined", "transcript", "visual"] = "combined",
):
    query = " ".join(q.split())
    if not query:
        raise HTTPException(status_code=422, detail="Enter a search question.")
    if len(query.split()) > 256:
        raise HTTPException(
            status_code=422, detail="Search question is too long (256 tokens maximum)."
        )
    selected = list(dict.fromkeys(video_ids or []))
    with connect() as db:
        if selected:
            existing = db.execute(
                "SELECT id FROM videos WHERE id = ANY(%s)", (selected,)
            ).fetchall()
            if len(existing) != len(selected):
                raise HTTPException(status_code=422, detail="A selected video was not found.")
        videos = db.execute(
            "SELECT id, title, transcript_state, visual_state FROM videos "
            "WHERE status = 'ready' AND (%s::uuid[] IS NULL OR id = ANY(%s::uuid[]))",
            (selected or None, selected or None),
        ).fetchall()
        has_text = mode != "visual" and any(v["transcript_state"] == "present" for v in videos)
        has_visual = mode != "transcript" and any(v["visual_state"] == "ready" for v in videos)
        if not (has_text or has_visual or mode == "combined" and videos):
            return SearchResponse(state="no_searchable_videos", results=[])
        register_vector(db)
        transcript_rows = []
        if has_text:
            with _text_lock:
                model = _model()
                if len(model.tokenizer.encode(query, add_special_tokens=True)) > 256:
                    raise HTTPException(
                        status_code=422, detail="Search question is too long (256 tokens maximum)."
                    )
                vector = model.encode([query], normalize_embeddings=True, convert_to_numpy=True)[0]
            if not all(math.isfinite(float(value)) for value in vector):
                raise HTTPException(
                    status_code=503, detail="Search model returned an invalid embedding."
                )
            cutoff = get_settings().search_similarity_cutoff
            if not 0 <= cutoff <= 1:
                raise RuntimeError("PRISM_SEARCH_SIMILARITY_CUTOFF must be between 0 and 1")
            transcript_rows = db.execute(
                "SELECT p.video_id, v.title AS video_title, p.start_seconds, p.end_seconds, "
                "p.text AS excerpt, p.ordinal, f.ordinal AS frame_ordinal, "
                "f.time_seconds AS preview_time_seconds, p.embedding <=> %s AS distance "
                "FROM passages AS p JOIN videos AS v ON v.id = p.video_id "
                "LEFT JOIN LATERAL (SELECT ordinal, time_seconds FROM frames "
                "WHERE video_id = p.video_id "
                "ORDER BY abs(time_seconds - p.start_seconds), ordinal LIMIT 1) AS f ON true "
                "WHERE v.status = 'ready' AND v.transcript_state = 'present' "
                "AND (%s::uuid[] IS NULL OR p.video_id = ANY(%s::uuid[])) "
                "AND p.embedding <=> %s <= %s "
                "ORDER BY distance, p.video_id, p.start_seconds, p.ordinal LIMIT 100",
                (vector, selected or None, selected or None, vector, 1 - cutoff),
            ).fetchall()
        frame_rows = []
        if has_visual:
            with _visual_lock:
                vector = embed_query(query)
            if not all(math.isfinite(float(value)) for value in vector):
                raise HTTPException(
                    status_code=503, detail="Visual model returned an invalid embedding."
                )
            cutoff = get_settings().visual_similarity_cutoff
            silent_cutoff = get_settings().silent_visual_similarity_cutoff
            if not 0 <= cutoff <= 1 or not 0 <= silent_cutoff <= 1:
                raise RuntimeError("Visual similarity cutoffs must be between 0 and 1")
            frame_rows = db.execute(
                "SELECT f.video_id, v.title AS video_title, f.ordinal AS frame_ordinal, "
                "f.time_seconds AS preview_time_seconds, v.duration_seconds, "
                "f.embedding <=> %s AS distance FROM frames AS f "
                "JOIN videos AS v ON v.id = f.video_id "
                "WHERE v.status = 'ready' AND v.visual_state = 'ready' AND f.model_revision = %s "
                "AND (%s::uuid[] IS NULL OR f.video_id = ANY(%s::uuid[])) "
                "AND f.embedding <=> %s <= "
                "CASE WHEN v.transcript_state = 'none' THEN %s ELSE %s END "
                "ORDER BY distance, f.video_id, f.ordinal LIMIT 100",
                (
                    vector,
                    VISUAL_REVISION,
                    selected or None,
                    selected or None,
                    vector,
                    1 - silent_cutoff,
                    1 - cutoff,
                ),
            ).fetchall()

    merged: list[tuple[float, SearchResult]] = []

    def add_candidate(score: float, candidate: SearchResult) -> None:
        overlapping = next(
            (
                i
                for i, (_, prior) in enumerate(merged)
                if prior.video_id == candidate.video_id
                and min(prior.end_seconds, candidate.end_seconds)
                > max(prior.start_seconds, candidate.start_seconds)
            ),
            None,
        )
        if overlapping is None:
            merged.append((score, candidate))
            return
        previous_score, previous = merged[overlapping]
        if candidate.evidence[0] not in previous.evidence:
            previous.evidence.append(candidate.evidence[0])
            previous.excerpt = previous.excerpt or candidate.excerpt
            if candidate.evidence == ["frame"]:
                previous.preview_time_seconds = candidate.preview_time_seconds
                previous.preview_url = candidate.preview_url
            merged[overlapping] = (previous_score + score, previous)

    for rank, row in enumerate(transcript_rows, 1):
        add_candidate(1 / (60 + rank), _candidate(row, frame=False))
    transcript_count = len(merged)
    for rank, row in enumerate(frame_rows, 1):
        add_candidate(1 / (60 + rank), _candidate(row, frame=True))
    if mode == "combined":
        chosen = merged[:5] + merged[transcript_count : transcript_count + 5]
        chosen += merged[5:transcript_count][: 10 - len(chosen)]
    else:
        chosen = merged[:10]
    results = [item for _, item in chosen]
    query_words = _tokens(query)
    title_results = [
        VideoResult(
            video_id=v["id"], video_title=v["title"], playback_url=f"/videos/{v['id']}/media"
        )
        for v in videos
        if mode == "combined" and _title_matches(query_words, v["title"])
    ]
    return SearchResponse(
        state="results" if results or title_results else "no_matches",
        results=results,
        video_results=title_results,
    )
