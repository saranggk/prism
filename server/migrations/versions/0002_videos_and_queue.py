"""Persist uploads and install the durable PgQueuer tables."""

from alembic import op
from pgqueuer.adapters.persistence.qb import QueryBuilderEnvironment
from pgqueuer.domain.settings import DBSettings, Durability

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE videos (
            id UUID PRIMARY KEY,
            title TEXT NOT NULL,
            source_path TEXT NOT NULL UNIQUE,
            duration_seconds DOUBLE PRECISION NOT NULL CHECK (duration_seconds > 0),
            status TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'ready', 'failed')),
            current_step TEXT,
            error TEXT,
            job_id BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX videos_created_at_idx ON videos (created_at DESC)")
    op.execute("""
        CREATE TABLE stage_checkpoints (
            video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
            stage TEXT NOT NULL,
            attempt_token UUID,
            completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (video_id, stage)
        )
    """)
    op.get_bind().exec_driver_sql(
        QueryBuilderEnvironment(DBSettings(durability=Durability.durable)).build_install_query()
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(QueryBuilderEnvironment().build_uninstall_query())
    op.execute("DROP TABLE stage_checkpoints")
    op.execute("DROP TABLE videos")
