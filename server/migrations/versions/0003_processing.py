"""Store attempt-owned processing outputs and searchable passages."""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE videos ADD COLUMN attempt_token UUID")
    op.execute("ALTER TABLE videos ADD COLUMN interrupted_attempts INTEGER NOT NULL DEFAULT 0")
    op.execute(
        "ALTER TABLE videos ADD COLUMN transcript_state TEXT "
        "CHECK (transcript_state IN ('present', 'none'))"
    )
    op.execute("ALTER TABLE stage_checkpoints ADD COLUMN version TEXT NOT NULL DEFAULT 'legacy'")
    op.execute("""
        CREATE TABLE frames (
            video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            time_seconds DOUBLE PRECISION NOT NULL CHECK (time_seconds >= 0),
            path TEXT NOT NULL,
            PRIMARY KEY (video_id, ordinal)
        )
    """)
    op.execute("""
        CREATE TABLE transcript_segments (
            video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            start_seconds DOUBLE PRECISION NOT NULL,
            end_seconds DOUBLE PRECISION NOT NULL,
            text TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('captions', 'whisper')),
            PRIMARY KEY (video_id, ordinal),
            CHECK (start_seconds >= 0 AND end_seconds > start_seconds)
        )
    """)
    op.execute("""
        CREATE TABLE passages (
            video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            start_seconds DOUBLE PRECISION NOT NULL,
            end_seconds DOUBLE PRECISION NOT NULL,
            text TEXT NOT NULL,
            segment_start_ordinal INTEGER NOT NULL,
            segment_end_ordinal INTEGER NOT NULL,
            embedding vector(384) NOT NULL,
            model_revision TEXT NOT NULL,
            PRIMARY KEY (video_id, ordinal),
            CHECK (start_seconds >= 0 AND end_seconds > start_seconds)
        )
    """)
    op.execute("CREATE INDEX passages_video_time_idx ON passages (video_id, start_seconds)")


def downgrade() -> None:
    op.execute("DROP TABLE passages")
    op.execute("DROP TABLE transcript_segments")
    op.execute("DROP TABLE frames")
    op.execute("ALTER TABLE stage_checkpoints DROP COLUMN version")
    op.execute("ALTER TABLE videos DROP COLUMN transcript_state")
    op.execute("ALTER TABLE videos DROP COLUMN interrupted_attempts")
    op.execute("ALTER TABLE videos DROP COLUMN attempt_token")
