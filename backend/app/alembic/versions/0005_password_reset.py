"""Email-bound one-use password reset credentials."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004_model_config"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("passwordreset",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_passwordreset_token_hash", "passwordreset", ["token_hash"], unique=True)


def downgrade():
    op.drop_table("passwordreset")
