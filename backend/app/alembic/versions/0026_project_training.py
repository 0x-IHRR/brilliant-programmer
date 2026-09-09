"""Freeze project module inputs, route bindings and public material origins."""

from alembic import op
import sqlalchemy as sa

revision = "0026_project_training"
down_revision = "0024_jd_route"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("project_topic",
        sa.Column("topic_id", sa.Uuid(), sa.ForeignKey("topic.id"), primary_key=True),
        sa.Column("project_run_id", sa.Uuid(), sa.ForeignKey("project_run.id"), nullable=False))
    op.create_index("ix_project_topic_project_run_id", "project_topic", ["project_run_id"])
    op.create_table("project_training_input",
        sa.Column("id", sa.Uuid(), sa.ForeignKey("topic_job.id"), primary_key=True),
        sa.Column("topic_id", sa.Uuid(), sa.ForeignKey("topic.id"), nullable=False),
        sa.Column("project_run_id", sa.Uuid(), sa.ForeignKey("project_run.id"), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("project_map", sa.JSON(), nullable=False))
    op.create_index("ix_project_training_input_topic_id", "project_training_input", ["topic_id"])
    op.create_table("project_training_version",
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("topic_version.id"), primary_key=True),
        sa.Column("input_id", sa.Uuid(), sa.ForeignKey("project_training_input.id"), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False))
    op.create_table("project_training_materials",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("training_run.id"), primary_key=True),
        sa.Column("origins", sa.JSON(), nullable=False))
    for table in ("project_topic", "project_training_input", "project_training_version", "project_training_materials"):
        op.execute(f"CREATE TRIGGER project_training_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION topic_snapshot_immutable()")
    op.execute("""CREATE OR REPLACE FUNCTION topic_goal_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.selection->>'entry' IN ('free_topic', 'jd', 'project') AND
        (NEW.selection::jsonb IS DISTINCT FROM OLD.selection::jsonb OR NEW.target::jsonb IS DISTINCT FROM OLD.target::jsonb)
      THEN RAISE EXCEPTION 'confirmed topic goal is immutable'; END IF;
      RETURN NEW;
    END $$""")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM project_topic)")).scalar():
        raise RuntimeError("retain project provenance and learning history")
    for table in ("project_training_materials", "project_training_version", "project_training_input", "project_topic"):
        op.drop_table(table)
