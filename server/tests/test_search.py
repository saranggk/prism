"""Search through the HTTP boundary with real PostgreSQL vector ranking."""

import os
from uuid import uuid4

import numpy as np
import psycopg


class QueryModel:
    class Tokenizer:
        def encode(self, text, add_special_tokens=True):
            return text.split()

    tokenizer = Tokenizer()

    def encode(self, texts, **kwargs):
        vector = np.zeros(384, dtype=np.float32)
        vector[0] = 1
        return np.array([vector for _ in texts])


def seed(title, status, passages, tmp_path):
    video_id = uuid4()
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        db.execute(
            "INSERT INTO videos (id, title, source_path, duration_seconds, "
            "status, transcript_state) "
            "VALUES (%s, %s, %s, 30, %s, 'present')",
            (video_id, title, str(tmp_path / f"{video_id}.mp4"), status),
        )
        for ordinal, (start, end, content, vector) in enumerate(passages):
            db.execute(
                "INSERT INTO passages (video_id, ordinal, start_seconds, end_seconds, text, "
                "segment_start_ordinal, segment_end_ordinal, embedding, model_revision) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, 'test')",
                (video_id, ordinal, start, end, content, ordinal, ordinal, vector),
            )
        db.execute(
            "INSERT INTO frames (video_id, ordinal, time_seconds, path) VALUES (%s, 0, 4, %s)",
            (video_id, str(tmp_path / f"{video_id}.jpg")),
        )
    return video_id


def test_search_filters_ready_videos_and_deduplicates_overlapping_passages(api, monkeypatch):
    from prism import search

    client, tmp_path = api
    monkeypatch.setattr(search, "load_embedder", QueryModel)
    first = seed(
        "First",
        "ready",
        [
            (5, 12, "database setup", "[1," + "0," * 382 + "0]"),
            (10, 16, "overlapping setup", "[0.95,0.05," + "0," * 381 + "0]"),
        ],
        tmp_path,
    )
    second = seed(
        "Second", "ready", [(18, 22, "another database", "[1," + "0," * 382 + "0]")], tmp_path
    )
    third = seed(
        "Third", "ready", [(25, 28, "connection details", "[1," + "0," * 382 + "0]")], tmp_path
    )
    seed("Processing", "processing", [(4, 8, "hidden", "[1," + "0," * 382 + "0]")], tmp_path)

    all_results = client.get("/search", params={"q": "where database"}).json()
    assert all_results["state"] == "results"
    assert {item["video_id"] for item in all_results["results"]} == {
        str(first),
        str(second),
        str(third),
    }
    assert len(all_results["results"]) == 3
    assert all(item["preview_time_seconds"] == 4 for item in all_results["results"])
    assert {item["playback_url"] for item in all_results["results"]} == {
        f"/videos/{first}/media",
        f"/videos/{second}/media",
        f"/videos/{third}/media",
    }

    two_selected = client.get(
        "/search",
        params=[("q", "where database"), ("video_ids", str(first)), ("video_ids", str(second))],
    ).json()
    assert {item["video_id"] for item in two_selected["results"]} == {str(first), str(second)}

    filtered = client.get(
        "/search", params={"q": "where database", "video_ids": str(second)}
    ).json()
    assert [item["video_id"] for item in filtered["results"]] == [str(second)]
    assert len(all_results["results"]) > len(filtered["results"])
    assert (
        client.get("/search", params={"q": "where database", "video_ids": str(uuid4())}).status_code
        == 422
    )


def test_search_rejects_empty_or_long_queries_and_explains_empty_states(api, monkeypatch):
    from prism import search

    client, tmp_path = api
    monkeypatch.setattr(search, "load_embedder", QueryModel)
    assert client.get("/search", params={"q": "   "}).status_code == 422
    assert client.get("/search", params={"q": "word " * 257}).status_code == 422
    assert client.get("/search", params={"q": "database"}).json()["state"] == "no_searchable_videos"
    seed("Ready", "ready", [(2, 5, "unrelated", "[0,1," + "0," * 381 + "0]")], tmp_path)
    response = client.get("/search", params={"q": "database"})
    assert response.status_code == 200
    assert response.json()["state"] == "no_matches"
    assert response.json()["results"] == []


def test_visual_search_finds_silent_frame_and_keeps_title_match_separate(api, monkeypatch):
    from prism import search
    from prism.visual import MODEL_REVISION

    client, tmp_path = api
    video_id = seed("Database connection demo", "ready", [], tmp_path)
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        db.execute(
            "UPDATE videos SET transcript_state = 'none', visual_state = 'ready' WHERE id = %s",
            (video_id,),
        )
        db.execute(
            "UPDATE frames SET embedding = %s::vector, model_revision = %s WHERE video_id = %s",
            ("[1," + "0," * 510 + "0]", MODEL_REVISION, video_id),
        )
    query_vector = np.zeros(512, dtype=np.float32)
    query_vector[0] = 1
    monkeypatch.setattr(search, "embed_query", lambda query: query_vector)

    payload = client.get("/search", params={"q": "database connection"}).json()
    assert payload["state"] == "results"
    assert len(payload["results"]) == 1
    assert payload["results"][0]["evidence"] == ["frame"]
    assert payload["results"][0]["excerpt"] is None
    assert payload["results"][0]["preview_time_seconds"] == 4
    assert payload["video_results"][0]["video_id"] == str(video_id)
    assert payload["video_results"][0]["evidence"] == "title"
    assert (
        client.get("/search", params={"q": "database connection", "mode": "transcript"}).json()[
            "state"
        ]
        == "no_searchable_videos"
    )
    assert (
        client.get(
            "/search", params={"q": "database connection", "video_ids": str(uuid4())}
        ).status_code
        == 422
    )


def test_title_only_match_does_not_claim_a_moment(api):
    client, tmp_path = api
    video_id = seed("Database connection demo", "ready", [], tmp_path)
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        db.execute("UPDATE videos SET transcript_state = 'none' WHERE id = %s", (video_id,))
    payload = client.get("/search", params={"q": "database connection"}).json()
    assert payload["results"] == []
    assert payload["video_results"][0]["video_id"] == str(video_id)
