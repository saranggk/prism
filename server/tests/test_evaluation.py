"""Hand-calculated examples for the small retrieval evaluation."""

import pytest

from prism.evaluate import Interval, score_case, summarize


def test_answerable_score_uses_top_five_and_actual_return_count():
    gold = [Interval("css", 10, 20)]
    results = [
        Interval("ajax", 10, 20),
        Interval("css", 12, 22),
        Interval("css", 30, 40),
    ]
    score = score_case(results, gold)
    assert score.hit_at_5 is True
    assert score.precision_at_5 == pytest.approx(1 / 3)
    assert score.start_error_seconds == 2
    assert score.interval_iou == pytest.approx(8 / 12)
    assert score.returned_count == 3


def test_unanswerable_result_is_a_false_match_without_timestamp_sample():
    score = score_case([Interval("tcp", 1, 9)], [])
    assert score.hit_at_5 is None
    assert score.precision_at_5 is None
    assert score.false_match is True
    assert score.start_error_seconds is None
    assert score.interval_iou is None
    assert score_case([], []).false_match is False


def test_wrong_video_is_not_a_timestamp_sample_and_aggregate_denominators_are_clear():
    miss = score_case([Interval("ajax", 10, 20)], [Interval("css", 10, 20)])
    hit = score_case([Interval("css", 12, 22)], [Interval("css", 10, 20)])
    negative = score_case([Interval("tcp", 1, 9)], [])
    assert miss.hit_at_5 is False
    assert miss.start_error_seconds is None
    summary = summarize([miss, hit, negative])
    assert summary["answerable_queries"] == 2
    assert summary["unanswerable_queries"] == 1
    assert summary["hit_at_5"] == pytest.approx(0.5)
    assert summary["precision_at_5"] == pytest.approx(0.5)
    assert summary["timestamp_samples"] == 1
    assert summary["mean_start_error_seconds"] == 2
    assert summary["false_match_rate"] == 1
