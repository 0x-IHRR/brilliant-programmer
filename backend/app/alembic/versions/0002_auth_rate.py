"""Bound local authentication attempts across API processes."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('auth_rate', sa.Column('key', sa.String(64), primary_key=True), sa.Column('minute', sa.BigInteger(), nullable=False), sa.Column('count', sa.BigInteger(), nullable=False))


def downgrade():
    op.drop_table('auth_rate')
