"""Retained draft collections; current snapshots stay unchanged and import lazily."""
from alembic import op
import sqlalchemy as sa

revision = "0014_draft_conflicts"
down_revision = "0013_config_revocation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("draft_collection",
        sa.Column("scope_key", sa.String(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("training_run.id"), nullable=False),
        sa.Column("help_id", sa.Uuid(), sa.ForeignKey("concept_help.id")),
        sa.Column("data", sa.JSON(), nullable=False))
    op.create_index("ix_draft_collection_run_id", "draft_collection", ["run_id"])


def downgrade():
    # Downgrade cannot silently discard retained conflicts or deletion tombstones.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT EXISTS(SELECT 1 FROM draft_collection)")).scalar():
        raise RuntimeError("draft collections exist; retain conflict and deletion facts")
    op.drop_table("draft_collection")
