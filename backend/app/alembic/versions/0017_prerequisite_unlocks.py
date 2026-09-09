"""Versioned learning-unit openings; preserve only previously public case units."""
from alembic import op
import sqlalchemy as sa

revision = "0017_prerequisite_unlocks"
down_revision = "0016_capability_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("opened_unit",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), primary_key=True),
        sa.Column("catalog_version", sa.String(), primary_key=True),
        sa.Column("capability_id", sa.String(), primary_key=True),
        sa.Column("difficulty", sa.String(), primary_key=True),
        sa.Column("background_id", sa.String(), primary_key=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False))
    op.execute("""INSERT INTO opened_unit
    SELECT user_id, selection->>'catalog_version', target->>'capability_id',
      target->>'difficulty', target->>'background_id', MIN(created_at), 'legacy_public_case', '[]'::json
    FROM training_run WHERE candidate IS NOT NULL AND json_typeof(candidate)='object'
      AND selection->>'catalog_version' IS NOT NULL
    GROUP BY user_id, selection->>'catalog_version', target->>'capability_id', target->>'difficulty', target->>'background_id'
    """)
    op.execute("""CREATE FUNCTION opened_unit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'learning-unit openings are immutable'; END $$""")
    op.execute("CREATE TRIGGER opened_unit_immutable BEFORE UPDATE OR DELETE ON opened_unit FOR EACH ROW EXECUTE FUNCTION opened_unit_immutable()")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM opened_unit)")).scalar():
        raise RuntimeError("retain existing learning-unit openings")
    op.drop_table("opened_unit")
    op.execute("DROP FUNCTION opened_unit_immutable()")
