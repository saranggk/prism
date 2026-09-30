"""Exact, filtered transcript passage search."""

import math
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

router = APIRouter()
_model_lock = threading.Lock()


@lru_cache(maxsize=1)
def _model():
    return load_embedder()


class SearchResult(BaseModel):
    video_id: UUID
    video_title: str
    start_seconds: float
    end_seconds: float
    excerpt: str
    preview_time_seconds: float | None
    preview_url: str | None
    playback_url: str


class SearchResponse(BaseModel):
    state: Literal["results", "no_searchable_videos", "no_matches"]
    results: list[SearchResult]
    provisional: bool = True


@router.get("/search", response_model=SearchResponse)
def search(
    q: Annotated[str, Query(min_length=1, max_length=1000)],
    video_ids: Annotated[list[UUID] | None, Query()] = None,
):
    query = " ".join(q.split())
    if not query:
        raise HTTPException(status_code=422, detail="Enter a search question.")
    # A cheap limit avoids loading the model for obviously abusive input.
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
        ready = db.execute(
            "SELECT count(*) AS count FROM videos "
            "WHERE status = 'ready' AND transcript_state = 'present' "
            "AND (%s::uuid[] IS NULL OR id = ANY(%s::uuid[]))",
            (selected or None, selected or None),
        ).fetchone()["count"]
        if not ready:
            return SearchResponse(state="no_searchable_videos", results=[])

        # FastAPI runs this synchronous endpoint in its thread pool. The model is
        # shared but inference is bounded to one CPU query at a time.
        with _model_lock:
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
        register_vector(db)
        cutoff = get_settings().search_similarity_cutoff
        if not 0 <= cutoff <= 1:
            raise RuntimeError("PRISM_SEARCH_SIMILARITY_CUTOFF must be between 0 and 1")
        rows = db.execute(
            "SELECT p.video_id, v.title AS video_title, p.start_seconds, p.end_seconds, "
            "p.text AS excerpt, p.ordinal, f.ordinal AS frame_ordinal, "
            "f.time_seconds AS preview_time_seconds, p.embedding <=> %s AS distance "
            "FROM passages AS p JOIN videos AS v ON v.id = p.video_id "
            "LEFT JOIN LATERAL (SELECT ordinal, time_seconds FROM frames "
            "WHERE video_id = p.video_id "
            "ORDER BY abs(time_seconds - p.start_seconds), ordinal LIMIT 1) "
            "AS f ON true "
            "WHERE v.status = 'ready' AND v.transcript_state = 'present' "
            "AND (%s::uuid[] IS NULL OR p.video_id = ANY(%s::uuid[])) "
            "AND p.embedding <=> %s <= %s "
            "ORDER BY distance, p.video_id, p.start_seconds, p.ordinal",
            (vector, selected or None, selected or None, vector, 1 - cutoff),
        ).fetchall()
    results: list[SearchResult] = []
    for row in rows:
        if any(
            item.video_id == row["video_id"]
            and min(item.end_seconds, row["end_seconds"])
            > max(item.start_seconds, row["start_seconds"])
            for item in results
        ):
            continue
        video_id = row["video_id"]
        frame = row["frame_ordinal"]
        results.append(
            SearchResult(
                video_id=video_id,
                video_title=row["video_title"],
                start_seconds=row["start_seconds"],
                end_seconds=row["end_seconds"],
                excerpt=row["excerpt"],
                preview_time_seconds=row["preview_time_seconds"],
                preview_url=f"/videos/{video_id}/frames/{frame}" if frame is not None else None,
                playback_url=f"/videos/{video_id}/media",
            )
        )
        if len(results) == 10:
            break
    return SearchResponse(state="results" if results else "no_matches", results=results)
