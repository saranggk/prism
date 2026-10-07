"""Manual collections of ordered ranges in existing source videos."""

import math
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from prism.jobs import connect

router = APIRouter()


class CollectionItem(BaseModel):
    id: UUID
    video_id: UUID
    video_title: str
    start_seconds: float
    end_seconds: float
    note: str
    position: int
    playback_url: str


class Collection(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    items: list[CollectionItem]


class CollectionTitle(BaseModel):
    title: str = Field(max_length=100)


class NewItem(BaseModel):
    video_id: UUID
    start_seconds: float
    end_seconds: float
    note: str = Field(default="", max_length=500)


class ItemEdit(BaseModel):
    start_seconds: float
    end_seconds: float
    note: str = Field(default="", max_length=500)


class ItemOrder(BaseModel):
    item_ids: list[UUID]


def _title(value: str) -> str:
    title = value.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Enter a collection name.")
    return title


def _range(db, video_id: UUID, start: float, end: float) -> None:
    video = db.execute(
        "SELECT duration_seconds, status FROM videos WHERE id = %s", (video_id,)
    ).fetchone()
    if video is None:
        raise HTTPException(status_code=422, detail="Source video was not found.")
    if video["status"] != "ready":
        raise HTTPException(status_code=422, detail="Source video is not ready.")
    valid = (
        math.isfinite(start)
        and math.isfinite(end)
        and 0 <= start < end <= video["duration_seconds"]
    )
    if not valid:
        raise HTTPException(status_code=422, detail="Choose a range inside the source video.")


def _item_rows(db, collection_ids: list[UUID]) -> list[dict]:
    return db.execute(
        "SELECT i.*, v.title AS video_title FROM collection_items AS i "
        "JOIN videos AS v ON v.id = i.video_id "
        "WHERE i.collection_id = ANY(%s::uuid[]) "
        "ORDER BY i.collection_id, i.position, i.created_at, i.id",
        (collection_ids,),
    ).fetchall()


def _model(row: dict, items: list[dict]) -> Collection:
    return Collection(
        **row,
        items=[
            CollectionItem(
                **item, playback_url=f"/videos/{item['video_id']}/media"
            )
            for item in items
        ],
    )


def _collection(db, collection_id: UUID) -> Collection:
    row = db.execute("SELECT * FROM collections WHERE id = %s", (collection_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Collection not found.")
    return _model(row, _item_rows(db, [collection_id]))


def _lock(db, collection_id: UUID) -> None:
    row = db.execute("SELECT id FROM collections WHERE id = %s FOR UPDATE", (collection_id,))
    if row.fetchone() is None:
        raise HTTPException(status_code=404, detail="Collection not found.")


@router.get("/collections", response_model=list[Collection])
def list_collections() -> list[Collection]:
    with connect() as db:
        rows = db.execute("SELECT * FROM collections ORDER BY updated_at DESC, id").fetchall()
        if not rows:
            return []
        grouped: dict[UUID, list[dict]] = {row["id"]: [] for row in rows}
        for item in _item_rows(db, [row["id"] for row in rows]):
            grouped[item["collection_id"]].append(item)
        return [_model(row, grouped[row["id"]]) for row in rows]


@router.post("/collections", response_model=Collection, status_code=201)
def create_collection(value: CollectionTitle) -> Collection:
    collection_id = uuid4()
    with connect() as db, db.transaction():
        db.execute(
            "INSERT INTO collections (id, title) VALUES (%s, %s)",
            (collection_id, _title(value.title)),
        )
        return _collection(db, collection_id)


@router.get("/collections/{collection_id}", response_model=Collection)
def get_collection(collection_id: UUID) -> Collection:
    with connect() as db:
        return _collection(db, collection_id)


@router.patch("/collections/{collection_id}", response_model=Collection)
def rename_collection(collection_id: UUID, value: CollectionTitle) -> Collection:
    with connect() as db, db.transaction():
        _lock(db, collection_id)
        db.execute(
            "UPDATE collections SET title = %s, updated_at = now() WHERE id = %s",
            (_title(value.title), collection_id),
        )
        return _collection(db, collection_id)


@router.delete("/collections/{collection_id}", status_code=204)
def delete_collection(collection_id: UUID) -> None:
    with connect() as db, db.transaction():
        removed = db.execute(
            "DELETE FROM collections WHERE id = %s RETURNING id", (collection_id,)
        ).fetchone()
        if removed is None:
            raise HTTPException(status_code=404, detail="Collection not found.")


@router.post("/collections/{collection_id}/items", response_model=Collection)
def add_item(collection_id: UUID, value: NewItem) -> Collection:
    with connect() as db, db.transaction():
        _lock(db, collection_id)
        _range(db, value.video_id, value.start_seconds, value.end_seconds)
        row = db.execute(
            "SELECT coalesce(max(position) + 1, 0) AS next_position FROM collection_items "
            "WHERE collection_id = %s",
            (collection_id,),
        ).fetchone()
        db.execute(
            "INSERT INTO collection_items "
            "(id, collection_id, video_id, start_seconds, end_seconds, note, position) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (uuid4(), collection_id, value.video_id, value.start_seconds, value.end_seconds,
             value.note.strip(), row["next_position"]),
        )
        db.execute("UPDATE collections SET updated_at = now() WHERE id = %s", (collection_id,))
        return _collection(db, collection_id)


@router.put("/collections/{collection_id}/items/order", response_model=Collection)
def reorder_items(collection_id: UUID, value: ItemOrder) -> Collection:
    with connect() as db, db.transaction():
        _lock(db, collection_id)
        rows = db.execute(
            "SELECT id FROM collection_items WHERE collection_id = %s", (collection_id,)
        ).fetchall()
        if len(value.item_ids) != len(rows) or set(value.item_ids) != {row["id"] for row in rows}:
            raise HTTPException(
                status_code=422, detail="Order must contain every collection item once."
            )
        db.execute(
            "UPDATE collection_items AS item SET position = desired.position FROM "
            "(SELECT id, ordinality - 1 AS position FROM "
            "unnest(%s::uuid[]) WITH ORDINALITY AS ordered(id, ordinality)) AS desired "
            "WHERE item.collection_id = %s AND item.id = desired.id "
            "AND item.position IS DISTINCT FROM desired.position",
            (value.item_ids, collection_id),
        )
        db.execute("UPDATE collections SET updated_at = now() WHERE id = %s", (collection_id,))
        return _collection(db, collection_id)


@router.patch("/collections/{collection_id}/items/{item_id}", response_model=Collection)
def edit_item(collection_id: UUID, item_id: UUID, value: ItemEdit) -> Collection:
    with connect() as db, db.transaction():
        _lock(db, collection_id)
        item = db.execute(
            "SELECT video_id FROM collection_items WHERE id = %s AND collection_id = %s",
            (item_id, collection_id),
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="Collection item not found.")
        _range(db, item["video_id"], value.start_seconds, value.end_seconds)
        db.execute(
            "UPDATE collection_items SET start_seconds = %s, end_seconds = %s, note = %s "
            "WHERE id = %s AND collection_id = %s",
            (value.start_seconds, value.end_seconds, value.note.strip(), item_id, collection_id),
        )
        db.execute("UPDATE collections SET updated_at = now() WHERE id = %s", (collection_id,))
        return _collection(db, collection_id)


@router.delete("/collections/{collection_id}/items/{item_id}", response_model=Collection)
def remove_item(collection_id: UUID, item_id: UUID) -> Collection:
    with connect() as db, db.transaction():
        _lock(db, collection_id)
        removed = db.execute(
            "DELETE FROM collection_items WHERE id = %s AND collection_id = %s RETURNING id",
            (item_id, collection_id),
        ).fetchone()
        if removed is None:
            raise HTTPException(status_code=404, detail="Collection item not found.")
        db.execute("UPDATE collections SET updated_at = now() WHERE id = %s", (collection_id,))
        return _collection(db, collection_id)
