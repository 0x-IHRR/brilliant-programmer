"""One encrypted model configuration per user."""
from alembic import op
import sqlalchemy as sa

revision = "0004_model_config"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_config",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), primary_key=True),
        sa.Column("version", sa.Uuid(), nullable=False, unique=True),
        sa.Column("service_url", sa.String(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("encrypted_key", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.String(), nullable=False),
    )


def downgrade():
    op.drop_table("model_config")
