"""Persistent config revocation and minimal draft-probe usage facts."""

from alembic import op
import sqlalchemy as sa

revision = "0013_config_revocation"
down_revision = "0012_guided"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "model_config",
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "probe_attempt",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("destination", sa.String(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("prompt_tokens", sa.BigInteger()),
        sa.Column("completion_tokens", sa.BigInteger()),
        sa.Column("total_tokens", sa.BigInteger()),
        sa.UniqueConstraint("operation_id", "number"),
    )
    op.create_index("ix_probe_attempt_user_id", "probe_attempt", ["user_id"])


def downgrade():
    op.drop_table("probe_attempt")
    op.drop_column("model_config", "revoked")
