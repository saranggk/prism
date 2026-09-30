"""Versioned visual frame vectors and independent indexing status."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE videos ADD COLUMN visual_state TEXT NOT NULL DEFAULT 'pending' "
        "CHECK (visual_state IN ('pending', 'indexing', 'ready', 'failed'))"
    )
    op.execute("ALTER TABLE videos ADD COLUMN visual_error TEXT")
    op.execute("ALTER TABLE frames ADD COLUMN embedding vector(512)")
    op.execute("ALTER TABLE frames ADD COLUMN model_revision TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE frames DROP COLUMN model_revision")
    op.execute("ALTER TABLE frames DROP COLUMN embedding")
    op.execute("ALTER TABLE videos DROP COLUMN visual_error")
    op.execute("ALTER TABLE videos DROP COLUMN visual_state")
