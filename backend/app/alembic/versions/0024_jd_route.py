"""Immutable JD provenance attached to Topic versions and shared jobs."""

from alembic import op
import sqlalchemy as sa

revision = "0024_jd_route"
down_revision = "0022_score_review"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("jd_topic", sa.Column("topic_id", sa.Uuid(), sa.ForeignKey("topic.id"), primary_key=True))
    op.create_table(
        "jd_document",
        sa.Column("id", sa.Uuid(), sa.ForeignKey("topic_job.id"), primary_key=True),
        sa.Column("topic_id", sa.Uuid(), sa.ForeignKey("topic.id"), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
    )
    op.create_index("ix_jd_document_topic_id", "jd_document", ["topic_id"])
    op.create_table(
        "jd_analysis",
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("jd_document.id"), primary_key=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
    )
    op.create_table(
        "jd_route",
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("topic_version.id"), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("jd_document.id"), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
    )
    op.create_index("ix_jd_route_document_id", "jd_route", ["document_id"])
    for table in ("jd_topic", "jd_document", "jd_analysis", "jd_route"):
        op.execute(f"CREATE TRIGGER jd_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION topic_snapshot_immutable()")
    op.execute("""CREATE OR REPLACE FUNCTION topic_goal_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.selection->>'entry' IN ('free_topic', 'jd') AND
        (NEW.selection::jsonb IS DISTINCT FROM OLD.selection::jsonb OR NEW.target::jsonb IS DISTINCT FROM OLD.target::jsonb)
      THEN RAISE EXCEPTION 'confirmed topic goal is immutable'; END IF;
      RETURN NEW;
    END $$""")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM jd_topic)")).scalar():
        raise RuntimeError("retain JD provenance and learning history")
    for table in ("jd_route", "jd_analysis", "jd_document", "jd_topic"):
        op.drop_table(table)
