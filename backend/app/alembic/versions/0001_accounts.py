"""Invited accounts, PostgreSQL facts."""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('user', sa.Column('email', sa.String(255), nullable=False), sa.Column('is_active', sa.Boolean(), nullable=False), sa.Column('is_superuser', sa.Boolean(), nullable=False), sa.Column('email_verified', sa.Boolean(), nullable=False), sa.Column('level', sa.String(), nullable=False), sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('hashed_password', sa.String(), nullable=False))
    op.create_index('ix_user_email', 'user', ['email'], unique=True)
    op.create_table('invitation', sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('code', sa.String(), nullable=False), sa.Column('status', sa.String(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.CheckConstraint("status IN ('unused', 'used', 'revoked')"))
    op.create_index('ix_invitation_code', 'invitation', ['code'], unique=True)


def downgrade():
    op.drop_table('invitation')
    op.drop_table('user')
