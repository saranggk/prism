"""Transient image and clip queries against indexed library frames."""

import math
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, UploadFile
from pgvector.psycopg import register_vector
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from prism.config import get_settings
from prism.jobs import connect
from prism.visual import MODEL_LOCK, MODEL_REVISION, load_visual_model

router = APIRouter()
MAX_QUERY_BYTES = 60 * 1024 * 1024
MAX_CLIP_SECONDS = 30
MAX_IMAGE_PIXELS = 25_000_000


class VisualQueryResult(BaseModel):
    video_id: UUID
    video_title: str
    frame_time_seconds: float
    frame_url: str
    playback_url: str
    query_time_seconds: float


class VisualQueryResponse(BaseModel):
    state: Literal["results", "no_searchable_videos", "no_matches"]
    results: list[VisualQueryResult]
    skipped_videos: list[str]


def _read_upload(file: UploadFile, destination: Path) -> None:
    size = 0
    with destination.open("wb") as output:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_QUERY_BYTES:
                raise HTTPException(status_code=413, detail="Query file exceeds 60 MiB.")
            output.write(chunk)
    if not size:
        raise HTTPException(status_code=422, detail="Choose a nonempty image or clip.")


def _image(path: Path) -> Image.Image:
    try:
        with Image.open(path) as source:
            if (
                source.format not in {"JPEG", "PNG"}
                or source.width * source.height > MAX_IMAGE_PIXELS
            ):
                raise ValueError("unsupported image")
            source.load()
            return source.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=422, detail="Use a valid JPEG or PNG image.") from exc


def _clip_frames(path: Path, directory: Path) -> list[tuple[float, Image.Image]]:
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-select_streams",
                "v:0",
                "-show_entries",
                "format=duration:stream=codec_name",
                "-of",
                "default=noprint_wrappers=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        fields = dict(line.split("=", 1) for line in probe.stdout.splitlines() if "=" in line)
        duration = float(fields["duration"])
        if not 0 < duration <= MAX_CLIP_SECONDS or not math.isfinite(duration):
            raise HTTPException(
                status_code=422, detail="Use an MP4 clip no longer than 30 seconds."
            )
        if fields.get("codec_name") not in {"h264", "hevc", "mpeg4", "av1", "vp9"}:
            raise HTTPException(status_code=422, detail="This MP4 video codec is unsupported.")
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-protocol_whitelist",
                "file",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-an",
                "-sn",
                "-vf",
                "fps=1/2,scale=512:512:force_original_aspect_ratio=decrease",
                "-frames:v",
                "16",
                "-y",
                str(directory / "%02d.jpg"),
            ],
            capture_output=True,
            check=True,
            timeout=60,
        )
    except HTTPException:
        raise
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=422, detail="Could not read this MP4 clip.") from exc
    paths = sorted(directory.glob("*.jpg"))
    if not paths:
        raise HTTPException(status_code=422, detail="This clip has no readable frames.")
    return [(i * 2.0, _image(frame)) for i, frame in enumerate(paths)]


@router.post("/search/visual", response_model=VisualQueryResponse)
def visual_query(
    file: UploadFile,
    video_ids: Annotated[list[UUID] | None, Query()] = None,
) -> VisualQueryResponse:
    selected = list(dict.fromkeys(video_ids or []))
    with connect() as db:
        if selected:
            found = db.execute("SELECT id FROM videos WHERE id = ANY(%s)", (selected,)).fetchall()
            if len(found) != len(selected):
                raise HTTPException(status_code=422, detail="A selected video was not found.")
        videos = db.execute(
            "SELECT id, title, visual_state FROM videos WHERE status = 'ready' "
            "AND (%s::uuid[] IS NULL OR id = ANY(%s::uuid[]))",
            (selected or None, selected or None),
        ).fetchall()
    skipped = [row["title"] for row in videos if row["visual_state"] != "ready"]
    if not any(row["visual_state"] == "ready" for row in videos):
        return VisualQueryResponse(state="no_searchable_videos", results=[], skipped_videos=skipped)

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".mp4"}:
        raise HTTPException(status_code=422, detail="Use a JPEG, PNG, or MP4 file.")
    with tempfile.TemporaryDirectory(prefix="prism-query-") as temp:
        path = Path(temp) / f"query{suffix}"
        _read_upload(file, path)
        samples = _clip_frames(path, Path(temp)) if suffix == ".mp4" else [(0.0, _image(path))]
        try:
            with MODEL_LOCK:
                vectors = load_visual_model().encode(
                    [image for _, image in samples],
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                )
        finally:
            for _, image in samples:
                image.close()

    cutoff = get_settings().image_similarity_cutoff
    if not 0 <= cutoff <= 1:
        raise RuntimeError("Image similarity cutoff must be between 0 and 1")
    candidates = []
    with connect() as db:
        register_vector(db)
        for (query_time, _), vector in zip(samples, vectors, strict=True):
            if not all(math.isfinite(float(value)) for value in vector):
                raise HTTPException(
                    status_code=503, detail="Visual model returned an invalid embedding."
                )
            rows = db.execute(
                "SELECT f.video_id, v.title, f.ordinal, f.time_seconds, "
                "f.embedding <=> %s AS distance FROM frames AS f "
                "JOIN videos AS v ON v.id = f.video_id "
                "WHERE v.status = 'ready' AND v.visual_state = 'ready' "
                "AND f.model_revision = %s AND f.embedding IS NOT NULL "
                "AND (%s::uuid[] IS NULL OR f.video_id = ANY(%s::uuid[])) "
                "AND f.embedding <=> %s <= %s "
                "ORDER BY distance, f.video_id, f.ordinal LIMIT 20",
                (vector, MODEL_REVISION, selected or None, selected or None, vector, 1 - cutoff),
            ).fetchall()
            candidates.extend((row["distance"], query_time, row) for row in rows)
    results = []
    for _, query_time, row in sorted(
        candidates, key=lambda item: (item[0], str(item[2]["video_id"]), item[2]["time_seconds"])
    ):
        if any(
            item.video_id == row["video_id"]
            and abs(item.frame_time_seconds - row["time_seconds"]) < 8
            for item in results
        ):
            continue
        video_id = row["video_id"]
        results.append(
            VisualQueryResult(
                video_id=video_id,
                video_title=row["title"],
                frame_time_seconds=row["time_seconds"],
                frame_url=f"/videos/{video_id}/frames/{row['ordinal']}",
                playback_url=f"/videos/{video_id}/media",
                query_time_seconds=query_time,
            )
        )
        if len(results) == 10:
            break
    return VisualQueryResponse(
        state="results" if results else "no_matches", results=results, skipped_videos=skipped
    )
