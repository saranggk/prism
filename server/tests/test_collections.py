"""Manual collections are validated and ordered through the HTTP interface."""

import os
from uuid import uuid4

import psycopg

WRITE = {"X-Prism-Request": "1"}


def ready_video(tmp_path, *, status="ready", duration=60):
    video_id = uuid4()
    with psycopg.connect(os.environ["PRISM_TEST_DATABASE_URL"].replace("+psycopg", "")) as db:
        db.execute(
            "INSERT INTO videos (id, title, source_path, duration_seconds, status) "
            "VALUES (%s, 'Source video', %s, %s, %s)",
            (video_id, str(tmp_path / f"{video_id}.mp4"), duration, status),
        )
    return str(video_id)


def create_collection(client, title="Research notes"):
    response = client.post("/collections", json={"title": title}, headers=WRITE)
    assert response.status_code == 201
    return response.json()


def test_collection_ranges_edit_order_remove_and_persist(api):
    client, tmp_path = api
    video_id = ready_video(tmp_path)
    collection = create_collection(client)
    collection_id = collection["id"]
    assert collection["items"] == []

    first = client.post(
        f"/collections/{collection_id}/items",
        json={"video_id": video_id, "start_seconds": 5, "end_seconds": 12, "note": "First"},
        headers=WRITE,
    )
    assert first.status_code == 200
    first_id = first.json()["items"][0]["id"]
    second = client.post(
        f"/collections/{collection_id}/items",
        json={"video_id": video_id, "start_seconds": 20, "end_seconds": 30},
        headers=WRITE,
    )
    assert second.status_code == 200
    second_id = second.json()["items"][1]["id"]

    changed = client.patch(
        f"/collections/{collection_id}/items/{first_id}",
        json={"start_seconds": 6, "end_seconds": 13, "note": "Updated"},
        headers=WRITE,
    )
    assert changed.status_code == 200
    assert changed.json()["items"][0]["note"] == "Updated"
    assert changed.json()["items"][0]["playback_url"] == f"/videos/{video_id}/media"

    reordered = client.put(
        f"/collections/{collection_id}/items/order",
        json={"item_ids": [second_id, first_id]},
        headers=WRITE,
    )
    assert [item["id"] for item in reordered.json()["items"]] == [second_id, first_id]
    assert [item["id"] for item in client.get("/collections").json()[0]["items"]] == [
        second_id,
        first_id,
    ]
    removed = client.delete(f"/collections/{collection_id}/items/{second_id}", headers=WRITE)
    assert [item["id"] for item in removed.json()["items"]] == [first_id]

    renamed = client.patch(
        f"/collections/{collection_id}", json={"title": "Saved moments"}, headers=WRITE
    )
    assert renamed.json()["title"] == "Saved moments"
    assert client.get(f"/collections/{collection_id}").json()["items"][0]["start_seconds"] == 6
    assert client.delete(f"/collections/{collection_id}", headers=WRITE).status_code == 204
    assert client.get(f"/collections/{collection_id}").status_code == 404


def test_collection_rejects_invalid_ranges_and_order_without_mutation(api):
    client, tmp_path = api
    video_id = ready_video(tmp_path)
    unready_id = ready_video(tmp_path, status="processing")
    collection_id = create_collection(client)["id"]
    path = f"/collections/{collection_id}/items"
    for payload in [
        {"video_id": video_id, "start_seconds": 10, "end_seconds": 10},
        {"video_id": video_id, "start_seconds": 59, "end_seconds": 61},
        {"video_id": unready_id, "start_seconds": 1, "end_seconds": 2},
        {"video_id": str(uuid4()), "start_seconds": 1, "end_seconds": 2},
    ]:
        assert client.post(path, json=payload, headers=WRITE).status_code == 422
    assert client.get(f"/collections/{collection_id}").json()["items"] == []

    added = client.post(
        path,
        json={"video_id": video_id, "start_seconds": 1, "end_seconds": 2},
        headers=WRITE,
    ).json()
    item_id = added["items"][0]["id"]
    assert client.put(
        f"/collections/{collection_id}/items/order",
        json={"item_ids": [str(uuid4())]},
        headers=WRITE,
    ).status_code == 422
    assert client.patch(
        f"{path}/{item_id}",
        json={"start_seconds": 1, "end_seconds": 62, "note": "wrong"},
        headers=WRITE,
    ).status_code == 422
    current = client.get(f"/collections/{collection_id}").json()["items"]
    assert [(item["start_seconds"], item["end_seconds"], item["note"]) for item in current] == [
        (1, 2, "")
    ]
