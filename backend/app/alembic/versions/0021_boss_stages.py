"""Versioned complete comparison snapshots and durable per-batch checkpoints."""

from alembic import op
import sqlalchemy as sa

revision = "0021_boss_stages"
down_revision = "0020_free_topic"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "independent_work", sa.Column("history_snapshot", sa.JSON(), nullable=True)
    )
    op.add_column(
        "independent_work", sa.Column("comparison_plan", sa.JSON(), nullable=True)
    )
    op.add_column(
        "independent_work",
        sa.Column(
            "comparison_results",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM independent_work WHERE history_snapshot::text <> 'null' OR comparison_plan::text <> 'null' OR comparison_results::text <> '[]')"
            )
        )
        .scalar()
    ):
        raise RuntimeError("retain complete history and comparison checkpoint facts")
    for field in ("comparison_results", "comparison_plan", "history_snapshot"):
        op.drop_column("independent_work", field)
