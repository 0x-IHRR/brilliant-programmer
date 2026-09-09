"""Round-owned editable drafts with optimistic versions, no expiry."""
from alembic import op
import sqlalchemy as sa

revision = "0011_draft"
down_revision = "0010_concept"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "training_draft",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("training_run.id"), primary_key=True),
        sa.Column("version", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("progress", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("training_draft")
