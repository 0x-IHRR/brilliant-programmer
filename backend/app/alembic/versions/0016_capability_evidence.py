"""Preserve original-answer order independently of later observations."""
from alembic import op
import sqlalchemy as sa

revision = "0016_capability_evidence"
down_revision = "0015_independent"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("capability_original_order",
        sa.Column("original_id", sa.Uuid(), sa.ForeignKey("training_submission.id"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("position", sa.BigInteger(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.UniqueConstraint("user_id", "position"))
    op.create_index("ix_capability_original_order_user_id", "capability_original_order", ["user_id"])
    op.execute("""INSERT INTO capability_original_order
        SELECT s.id, r.user_id,
        row_number() OVER (PARTITION BY r.user_id ORDER BY s.created_at, s.id),
        s.created_at, 'legacy_created_at_uuid'
        FROM training_submission s JOIN training_run r ON s.run_id=r.id
        WHERE s.kind='original' AND s.practice_help_id IS NULL""")
    op.execute("""CREATE FUNCTION capability_order_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'original order is immutable'; END $$""")
    op.execute("CREATE TRIGGER capability_order_immutable BEFORE UPDATE OR DELETE ON capability_original_order FOR EACH ROW EXECUTE FUNCTION capability_order_immutable()")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM capability_original_order)")).scalar():
        raise RuntimeError("retain original evidence ordering")
    op.drop_table("capability_original_order")
    op.execute("DROP FUNCTION capability_order_immutable()")
