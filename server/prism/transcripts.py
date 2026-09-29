"""Caption validation, speech fallback, and bounded passage grouping."""

import re
from dataclasses import dataclass
from pathlib import Path

from prism.config import get_settings
from prism.media import MediaError, MediaInfo, extract_caption_srt

WHISPER_REPO = "Systran/faster-whisper-small.en"
WHISPER_REVISION = "d1d751a5f8271d482d14ca55d9e2deeebbae577f"
EMBEDDING_REPO = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
CAPTION_VERSION = "captions-srt-v1"
WHISPER_VERSION = f"faster-whisper-small.en:{WHISPER_REVISION}:cpu-int8-vad"
PASSAGE_VERSION = f"all-MiniLM-L6-v2:{EMBEDDING_REVISION}:passages-v1"


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str
    source: str


@dataclass(frozen=True)
class Passage:
    start: float
    end: float
    text: str
    first_segment: int
    last_segment: int


def _srt_seconds(value: str) -> float:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_srt(text: str, duration: float) -> list[Segment]:
    blocks = re.split(r"\r?\n\s*\r?\n", text.strip())
    segments = []
    previous_start = -1.0
    for block in blocks:
        match = re.search(
            r"(?m)^(\d\d:\d\d:\d\d[,\.]\d{3}) --> "
            r"(\d\d:\d\d:\d\d[,\.]\d{3})(?:[^\n]*)\n([\s\S]+)$",
            block,
        )
        if not match:
            continue
        start, end = _srt_seconds(match[1]), _srt_seconds(match[2])
        content = re.sub(r"<[^>]+>", "", match[3])
        content = " ".join(content.split())
        if not content or not (
            0 <= previous_start <= start < end <= duration + 0.1
            or previous_start < 0
            and 0 <= start < end <= duration + 0.1
        ):
            return []
        segments.append(Segment(start, min(end, duration), content, "captions"))
        previous_start = start
    return segments


def captions(path: Path, info: MediaInfo) -> list[Segment]:
    for stream in info.caption_streams:
        if stream.get("codec_name") not in {"mov_text", "subrip", "webvtt"}:
            continue
        language = stream.get("tags", {}).get("language", "").lower()
        if language not in {"en", "eng", "", "und"}:
            continue
        try:
            segments = parse_srt(
                extract_caption_srt(path, stream["index"], info.duration), info.duration
            )
        except (KeyError, ValueError, MediaError):
            continue
        if segments and language in {"en", "eng"}:
            return segments
        if segments and language in {"", "und"}:
            # Unknown-language tracks need positive English detection.
            from langdetect import DetectorFactory, LangDetectException, detect

            DetectorFactory.seed = 0
            try:
                if detect(" ".join(item.text for item in segments)) == "en":
                    return segments
            except LangDetectException:
                pass
    return []


def transcribe(path: Path, duration: float) -> list[Segment]:
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model

    model_path = download_model(
        WHISPER_REPO,
        revision=WHISPER_REVISION,
        local_files_only=True,
        cache_dir=str(get_settings().storage_path / "models"),
    )
    model = WhisperModel(model_path, device="cpu", compute_type="int8", cpu_threads=4)
    output, _ = model.transcribe(str(path), language="en", vad_filter=True)
    segments = []
    for item in output:  # Transcription is lazy; model/decode errors arise here.
        text = " ".join(item.text.split())
        if text and 0 <= item.start < item.end <= duration + 0.5:
            segments.append(Segment(item.start, min(item.end, duration), text, "whisper"))
    return segments


def load_embedder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        EMBEDDING_REPO,
        revision=EMBEDDING_REVISION,
        device="cpu",
        local_files_only=True,
        cache_folder=str(get_settings().storage_path / "models"),
    )


def download_models() -> None:
    """Explicit setup step; normal ingestion never downloads a missing model."""
    from faster_whisper.utils import download_model
    from sentence_transformers import SentenceTransformer

    cache = get_settings().storage_path / "models"
    cache.mkdir(parents=True, exist_ok=True)
    download_model(WHISPER_REPO, revision=WHISPER_REVISION, cache_dir=str(cache))
    SentenceTransformer(
        EMBEDDING_REPO, revision=EMBEDDING_REVISION, device="cpu", cache_folder=str(cache)
    )


def build_passages(segments: list[Segment], tokenizer) -> list[Passage]:
    """Group complete source segments, splitting only text that exceeds 200 tokens."""
    pieces: list[tuple[int, Segment]] = []
    for ordinal, segment in enumerate(segments):
        words = segment.text.split()
        chunk: list[str] = []
        for word in words:
            if len(tokenizer.encode(word, add_special_tokens=True)) > 200:
                if chunk:
                    pieces.append(
                        (
                            ordinal,
                            Segment(segment.start, segment.end, " ".join(chunk), segment.source),
                        )
                    )
                    chunk = []
                remaining = word
                while remaining:
                    low, high = 1, len(remaining)
                    while low < high:
                        middle = (low + high + 1) // 2
                        if (
                            len(tokenizer.encode(remaining[:middle], add_special_tokens=True))
                            <= 200
                        ):
                            low = middle
                        else:
                            high = middle - 1
                    pieces.append(
                        (
                            ordinal,
                            Segment(segment.start, segment.end, remaining[:low], segment.source),
                        )
                    )
                    remaining = remaining[low:]
                continue
            candidate = " ".join([*chunk, word])
            if chunk and len(tokenizer.encode(candidate, add_special_tokens=True)) > 200:
                pieces.append(
                    (ordinal, Segment(segment.start, segment.end, " ".join(chunk), segment.source))
                )
                chunk = [word]
            else:
                chunk.append(word)
        if chunk:
            pieces.append(
                (ordinal, Segment(segment.start, segment.end, " ".join(chunk), segment.source))
            )
    passages = []
    cursor = 0
    while cursor < len(pieces):
        chosen = [pieces[cursor]]
        next_cursor = cursor + 1
        while next_cursor < len(pieces):
            next_piece = pieces[next_cursor]
            text = " ".join(piece.text for _, piece in [*chosen, next_piece])
            elapsed = next_piece[1].end - chosen[0][1].start
            if elapsed > 40 or len(tokenizer.encode(text, add_special_tokens=True)) > 200:
                break
            chosen.append(next_piece)
            next_cursor += 1
            if elapsed >= 20:
                break
        passages.append(
            Passage(
                chosen[0][1].start,
                chosen[-1][1].end,
                " ".join(piece.text for _, piece in chosen),
                chosen[0][0],
                chosen[-1][0],
            )
        )
        # One segment of context, except for an oversized split at the same interval.
        overlap = 1 if len(chosen) > 1 and next_cursor < len(pieces) else 0
        cursor = next_cursor - overlap
    return passages
