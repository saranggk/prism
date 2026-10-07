"""The research tools return scoped candidates and inspectable source records."""

import os
from uuid import uuid4

import numpy as np
import psycopg
import pytest


class QueryModel:
    class Tokenizer:
        def encode(self, text, add_special_tokens=True):
            return text.split()

    tokenizer = Tokenizer()

    def encode(self, texts, **kwargs):
        vector = np.zeros(384, dtype=np.float32)
        vector[0] = 1
        return np.array([vector for _ in texts])


def seed_video(tmp_path, *, title, transcript_state="present", visual_state="pending"):
    video_id = uuid4()
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        db.execute(
            "INSERT INTO videos (id, title, source_path, duration_seconds, status, "
            "transcript_state, visual_state) VALUES (%s, %s, %s, 30, 'ready', %s, %s)",
            (video_id, title, str(tmp_path / f"{video_id}.mp4"), transcript_state, visual_state),
        )
    return video_id


def test_search_tool_returns_only_scoped_timestamped_moments(api, monkeypatch):
    from prism import search
    from prism.agent_tools import search_moments

    _, tmp_path = api
    monkeypatch.setattr(search, "load_embedder", QueryModel)
    selected = seed_video(tmp_path, title="Database setup")
    other = seed_video(tmp_path, title="Other")
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        for video_id in (selected, other):
            db.execute(
                "INSERT INTO passages (video_id, ordinal, start_seconds, end_seconds, text, "
                "segment_start_ordinal, segment_end_ordinal, embedding, model_revision) "
                "VALUES (%s, 0, 5, 10, 'database setup', 0, 0, %s::vector, 'test')",
                (video_id, "[1," + "0," * 382 + "0]"),
            )
    result = search_moments("database setup", [selected], mode="transcript")
    assert result.state == "results"
    assert [(row.video_id, row.start_seconds, row.end_seconds) for row in result.moments] == [
        (selected, 5, 10)
    ]
    assert result.moments[0].evidence == ["transcript"]
    with pytest.raises(ValueError, match="Select at least one video"):
        search_moments("database setup", [])
    with pytest.raises(ValueError, match="selected video"):
        search_moments("database setup", [uuid4()])
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        db.execute("UPDATE videos SET status = 'processing' WHERE id = %s", (selected,))
    with pytest.raises(ValueError, match="not ready"):
        search_moments("database setup", [selected])


def test_inspection_tool_returns_stable_refs_and_rejects_other_videos(api):
    from prism.agent_tools import inspect_moment

    _, tmp_path = api
    selected = seed_video(tmp_path, title="Tutorial")
    other = seed_video(tmp_path, title="Other")
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        db.execute(
            "INSERT INTO transcript_segments (video_id, ordinal, start_seconds, "
            "end_seconds, text, source) VALUES (%s, 3, 10, 14, 'Click save', 'captions')",
            (selected,),
        )
        db.execute(
            "INSERT INTO frames (video_id, ordinal, time_seconds, path) VALUES (%s, 2, 12, %s)",
            (selected, str(frame)),
        )
    result = inspect_moment(selected, 12, [selected])
    assert result.video_id == selected
    assert [(row.ref.kind, row.ref.ordinal, row.text) for row in result.segments] == [
        ("segment", 3, "Click save")
    ]
    assert result.segments[0].ref.video_id == selected
    assert [(row.ref.kind, row.ref.ordinal, row.time_seconds) for row in result.frames] == [
        ("frame", 2, 12)
    ]
    with pytest.raises(ValueError, match="outside the selected videos"):
        inspect_moment(other, 12, [selected])


def test_silent_video_and_empty_search_have_explicit_states(api, monkeypatch):
    from prism import search
    from prism.agent_tools import inspect_moment, search_moments
    from prism.visual import MODEL_REVISION

    _, tmp_path = api
    silent = seed_video(
        tmp_path, title="Silent demo", transcript_state="none", visual_state="ready"
    )
    frame = tmp_path / "silent.jpg"
    frame.write_bytes(b"frame")
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        db.execute(
            "INSERT INTO frames (video_id, ordinal, time_seconds, path, embedding, model_revision) "
            "VALUES (%s, 0, 5, %s, %s::vector, %s)",
            (silent, str(frame), "[1," + "0," * 510 + "0]", MODEL_REVISION),
        )
    vector = np.zeros(512, dtype=np.float32)
    vector[0] = 1
    monkeypatch.setattr(search, "embed_query", lambda query: vector)
    found = search_moments("visible state", [silent], mode="visual")
    assert found.state == "results"
    assert [(row.video_id, row.evidence) for row in found.moments] == [(silent, ["frame"])]
    inspected = inspect_moment(silent, 5, [silent])
    assert inspected.segments == []
    assert inspected.transcript_state == "none"
    assert inspected.frames[0].ref.ordinal == 0
    vector[0] = 0
    vector[1] = 1
    assert search_moments("absent", [silent], mode="visual").state == "no_matches"


def test_title_only_match_is_not_a_research_moment(api):
    from prism.agent_tools import search_moments

    _, tmp_path = api
    video_id = seed_video(
        tmp_path, title="Database connection", transcript_state="none", visual_state="pending"
    )
    result = search_moments("database connection", [video_id])
    assert result.state == "no_searchable_videos"
    assert result.moments == []
    assert result.unsearchable_video_ids == [video_id]


def test_search_tool_identifies_unsearchable_videos_in_a_mixed_scope(api, monkeypatch):
    from prism import search
    from prism.agent_tools import search_moments

    _, tmp_path = api
    monkeypatch.setattr(search, "load_embedder", QueryModel)
    searchable = seed_video(tmp_path, title="Tutorial")
    unsearchable = seed_video(
        tmp_path, title="Silent pending demo", transcript_state="none", visual_state="pending"
    )
    result = search_moments("unrelated", [searchable, unsearchable])
    assert result.state == "no_matches"
    assert result.moments == []
    assert result.unsearchable_video_ids == [unsearchable]
