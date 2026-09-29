"""Small, explicit scoring primitives for labeled transcript retrieval."""

from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True)
class Interval:
    video_id: str
    start_seconds: float
    end_seconds: float

    def __post_init__(self) -> None:
        if self.start_seconds < 0 or self.end_seconds <= self.start_seconds:
            raise ValueError("Intervals need a nonnegative start and a later end.")


@dataclass(frozen=True)
class CaseScore:
    hit_at_5: bool | None
    precision_at_5: float | None
    false_match: bool | None
    start_error_seconds: float | None
    interval_iou: float | None
    returned_count: int


def _intersection(a: Interval, b: Interval) -> float:
    if a.video_id != b.video_id:
        return 0.0
    return max(0.0, min(a.end_seconds, b.end_seconds) - max(a.start_seconds, b.start_seconds))


def _iou(a: Interval, b: Interval) -> float:
    intersection = _intersection(a, b)
    if not intersection:
        return 0.0
    return intersection / (
        max(a.end_seconds, b.end_seconds) - min(a.start_seconds, b.start_seconds)
    )


def score_case(results: list[Interval], relevant: list[Interval]) -> CaseScore:
    """Score the first five results; empty gold means no answer in the chosen scope."""
    first_five = results[:5]
    if not relevant:
        return CaseScore(None, None, bool(first_five), None, None, len(first_five))

    relevant_count = sum(
        any(_intersection(result, gold) > 0 for gold in relevant) for result in first_five
    )
    same_video = next(
        (result for result in first_five if any(result.video_id == g.video_id for g in relevant)),
        None,
    )
    if same_video is None:
        start_error = None
        interval_iou = None
    else:
        nearest = min(
            (g for g in relevant if g.video_id == same_video.video_id),
            key=lambda g: abs(same_video.start_seconds - g.start_seconds),
        )
        start_error = abs(same_video.start_seconds - nearest.start_seconds)
        interval_iou = _iou(same_video, nearest)

    return CaseScore(
        hit_at_5=relevant_count > 0,
        precision_at_5=relevant_count / len(first_five) if first_five else 0.0,
        false_match=None,
        start_error_seconds=start_error,
        interval_iou=interval_iou,
        returned_count=len(first_five),
    )


def summarize(scores: list[CaseScore]) -> dict[str, int | float | None]:
    """Average positive-query precision; timestamp metrics need a correct video."""
    positive = [score for score in scores if score.hit_at_5 is not None]
    negative = [score for score in scores if score.false_match is not None]
    timed = [score for score in positive if score.start_error_seconds is not None]
    return {
        "answerable_queries": len(positive),
        "unanswerable_queries": len(negative),
        "hit_at_5": (
            sum(score.hit_at_5 is True for score in positive) / len(positive) if positive else None
        ),
        "precision_at_5": (
            mean(score.precision_at_5 for score in positive if score.precision_at_5 is not None)
            if positive
            else None
        ),
        "timestamp_samples": len(timed),
        "mean_start_error_seconds": (
            mean(
                score.start_error_seconds
                for score in timed
                if score.start_error_seconds is not None
            )
            if timed
            else None
        ),
        "mean_interval_iou": (
            mean(score.interval_iou for score in timed if score.interval_iou is not None)
            if timed
            else None
        ),
        "false_match_rate": (
            sum(score.false_match is True for score in negative) / len(negative)
            if negative
            else None
        ),
    }
