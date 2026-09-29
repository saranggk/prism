"""Bounded FFmpeg reads of local video files."""

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class MediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    start: float
    has_audio: bool
    caption_streams: tuple[dict, ...]


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, capture_output=True, text=True, check=True, timeout=timeout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise MediaError("Could not read the video media. Check the file and retry.") from exc


def probe(path: Path) -> MediaInfo:
    result = _run(
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
        30,
    )
    try:
        data = json.loads(result.stdout)
        streams = data["streams"]
        video = next(stream for stream in streams if stream["codec_type"] == "video")
        duration = float(data["format"]["duration"])
        start = float(video.get("start_time", 0))
        if not 0 < duration <= 900:
            raise ValueError("invalid duration")
    except (KeyError, StopIteration, ValueError, TypeError) as exc:
        raise MediaError("The video media is damaged or unsupported.") from exc
    return MediaInfo(
        duration,
        start,
        any(stream.get("codec_type") == "audio" for stream in streams),
        tuple(stream for stream in streams if stream.get("codec_type") == "subtitle"),
    )


def extract_frames(path: Path, destination: Path, info: MediaInfo) -> list[tuple[float, Path]]:
    destination.mkdir(parents=True, exist_ok=True)
    # select observes decoded presentation time; showinfo reports each selected
    # frame's actual PTS. Output numbering is only a file identity.
    result = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "info",
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
            "select='isnan(prev_selected_t)+gte(t-prev_selected_t,5)',showinfo",
            "-fps_mode",
            "vfr",
            "-q:v",
            "4",
            "-y",
            str(destination / "%05d.jpg"),
        ],
        min(1800, max(90, int(info.duration * 3))),
    )
    times = [
        float(value) - info.start
        for value in re.findall(r"Parsed_showinfo[^\n]*?pts_time:\s*([-\d.]+)", result.stderr)
    ]
    files = sorted(destination.glob("*.jpg"))
    if not files or len(files) != len(times):
        raise MediaError("Could not extract timestamped preview images.")
    return [
        (max(0.0, min(info.duration, time)), file) for time, file in zip(times, files, strict=True)
    ]


def extract_caption_srt(path: Path, stream_index: int, duration: float) -> str:
    result = _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(path),
            "-map",
            f"0:{stream_index}",
            "-f",
            "srt",
            "-",
        ],
        min(900, max(30, int(duration * 2))),
    )
    return result.stdout
