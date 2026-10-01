"""Validated local MP4 uploads and request guards."""

import json
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.responses import JSONResponse

from prism.config import get_settings
from prism.jobs import (
    get_video,
    list_videos,
    referenced_upload_ids,
    register_video,
    retry_video,
    retry_visual,
)
from prism.models import Video

logger = logging.getLogger(__name__)
router = APIRouter()
MAX_FILE_BYTES = 500 * 1024 * 1024
MAX_REQUEST_BYTES = 501 * 1024 * 1024
MAX_VISUAL_REQUEST_BYTES = 61 * 1024 * 1024
MAX_DURATION_SECONDS = 900


class UploadGuard:
    """Reject oversized bodies before multipart parsing and guard browser writes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope["headers"]}
        if headers.get(b"x-prism-request") != b"1":
            await JSONResponse({"detail": "X-Prism-Request header is required."}, status_code=403)(
                scope, receive, send
            )
            return
        origin = headers.get(b"origin")
        if origin is not None and origin.decode("latin-1") != get_settings().frontend_origin:
            await JSONResponse({"detail": "Origin is not allowed."}, status_code=403)(
                scope, receive, send
            )
            return
        if scope["method"] != "POST" or scope["path"] not in {"/videos", "/search/visual"}:
            await self.app(scope, receive, send)
            return
        visual_query = scope["path"] == "/search/visual"
        limit = MAX_VISUAL_REQUEST_BYTES if visual_query else MAX_REQUEST_BYTES
        try:
            content_length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            content_length = 0
        if content_length > limit:
            await self._too_large(scope, receive, send, visual_query)
            return
        # Consume into a disk-backed file first. The application never sees a partial
        # multipart request or a false Content-Length that hides an over-limit body.
        with tempfile.SpooledTemporaryFile(max_size=2 * 1024 * 1024) as body:
            size = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > limit:
                    await self._too_large(scope, receive, send, visual_query)
                    return
                body.write(chunk)
                if not message.get("more_body", False):
                    break
            body.seek(0)

            async def replay():
                chunk = body.read(1024 * 1024)
                return {"type": "http.request", "body": chunk, "more_body": bool(chunk)}

            await self.app(scope, replay, send)

    @staticmethod
    async def _too_large(scope, receive, send, visual_query=False):
        detail = (
            "Query upload exceeds the 60 MiB file limit."
            if visual_query
            else "Upload exceeds the 500 MiB video limit."
        )
        await JSONResponse({"detail": detail}, status_code=413)(scope, receive, send)


def _probe(path: Path) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        info = json.loads(result.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail="This file is not a valid MP4 video.") from exc
    container = info.get("format", {})
    if "mp4" not in container.get("format_name", ""):
        raise HTTPException(status_code=422, detail="Only MP4 videos are supported.")
    streams = info.get("streams", [])
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(video_streams) != 1 or len(audio_streams) > 1:
        raise HTTPException(
            status_code=422, detail="Use an MP4 with one video track and at most one audio track."
        )
    video = video_streams[0]
    if video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p":
        raise HTTPException(status_code=422, detail="Use H.264 video with yuv420p color format.")
    if video.get("width", 0) > 1920 or video.get("height", 0) > 1080:
        raise HTTPException(status_code=422, detail="Video resolution must be 1080p or lower.")
    if audio_streams and audio_streams[0].get("codec_name") != "aac":
        raise HTTPException(
            status_code=422, detail="Audio must use AAC, or the video may be silent."
        )
    languages = [stream.get("tags", {}).get("language", "").lower() for stream in streams]
    if any(language and language not in {"eng", "en", "und"} for language in languages):
        raise HTTPException(status_code=422, detail="Only English-language videos are supported.")
    try:
        duration = float(container["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Could not read the video duration.") from exc
    if not 0 < duration <= MAX_DURATION_SECONDS:
        raise HTTPException(status_code=422, detail="Video must be 15 minutes or shorter.")
    return duration


def _store(upload: UploadFile) -> Video:
    if not upload.filename or Path(upload.filename).suffix.lower() != ".mp4":
        raise HTTPException(status_code=422, detail="Choose an MP4 file.")
    title = "".join(char for char in Path(upload.filename).stem if char.isprintable()).strip()[:150]
    video_id = uuid4()
    uploads = get_settings().storage_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    temporary = uploads / f".partial-{video_id}"
    final_dir = uploads / str(video_id)
    temporary.mkdir()
    try:
        candidate = temporary / "source.mp4"
        size = 0
        with candidate.open("wb") as target:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise HTTPException(status_code=413, detail="Video exceeds the 500 MiB limit.")
                target.write(chunk)
        duration = _probe(candidate)
        temporary.rename(final_dir)
        try:
            return register_video(
                video_id, title or "Untitled video", final_dir / "source.mp4", duration
            )
        except Exception:
            # A lost connection around COMMIT has an ambiguous outcome. Keep the
            # file unless a fresh database read proves this attempt is orphaned.
            try:
                if str(video_id) not in referenced_upload_ids():
                    shutil.rmtree(final_dir)
            except psycopg.Error:
                logger.warning("Could not confirm whether upload %s committed", video_id)
            raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


@router.post("/videos", response_model=Video, status_code=201)
async def upload_video(request: Request) -> Video:
    try:
        async with request.form(max_files=1, max_fields=0) as form:
            files = form.getlist("file")
            if len(files) != 1 or not isinstance(files[0], StarletteUploadFile):
                raise HTTPException(status_code=422, detail="Choose one MP4 video file.")
            return await run_in_threadpool(_store, files[0])
    except HTTPException:
        raise
    except Exception as exc:
        if "Too many" in str(exc):
            raise HTTPException(status_code=422, detail="Choose one MP4 video file.") from exc
        raise


@router.get("/videos", response_model=list[Video])
def videos() -> list[Video]:
    return list_videos()


@router.get("/videos/{video_id}", response_model=Video)
def video(video_id: UUID) -> Video:
    return get_video(video_id)


@router.post("/videos/{video_id}/retry", response_model=Video)
def retry(video_id: UUID) -> Video:
    return retry_video(video_id)


@router.post("/videos/{video_id}/retry-visual", response_model=Video)
def retry_visual_index(video_id: UUID) -> Video:
    return retry_visual(video_id)


def reconcile_uploads() -> None:
    uploads = get_settings().storage_path / "uploads"
    if not uploads.exists():
        return
    try:
        referenced = referenced_upload_ids()
    except psycopg.Error:
        logger.warning("Upload reconciliation skipped because the database is unavailable")
        return
    now = time.time()
    for directory in uploads.iterdir():
        if (
            not directory.is_dir()
            or directory.is_symlink()
            or now - directory.stat().st_mtime < 3600
        ):
            continue
        name = directory.name
        if name.startswith(".partial-"):
            shutil.rmtree(directory)
            continue
        try:
            UUID(name)
        except ValueError:
            continue
        if name not in referenced:
            shutil.rmtree(directory)
