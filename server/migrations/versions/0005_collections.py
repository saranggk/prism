"""Persist ordered, editable ranges that point to source videos."""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE collections (
            id UUID PRIMARY KEY,
            title TEXT NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 100),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE collection_items (
            id UUID PRIMARY KEY,
            collection_id UUID NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            video_id UUID NOT NULL REFERENCES videos(id),
            start_seconds DOUBLE PRECISION NOT NULL,
            end_seconds DOUBLE PRECISION NOT NULL,
            note TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 500),
            position INTEGER NOT NULL CHECK (position >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (start_seconds >= 0 AND end_seconds > start_seconds)
        )
    """)
    op.execute(
        "CREATE INDEX collection_items_order_idx ON collection_items (collection_id, position)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE collection_items")
    op.execute("DROP TABLE collections")
