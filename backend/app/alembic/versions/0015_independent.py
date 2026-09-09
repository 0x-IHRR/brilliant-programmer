"""Explicit independent rounds; private comparisons and ordered immutable facts."""
from alembic import op
import sqlalchemy as sa

revision = "0015_independent"
down_revision = "0014_draft_conflicts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("training_run", sa.Column("launch_mode", sa.String(), nullable=False, server_default="practice"))
    op.add_column("training_run", sa.Column("origin_id", sa.Uuid(), sa.ForeignKey("training_run.id")))
    op.add_column("training_run", sa.Column("converted_sequence", sa.BigInteger()))
    op.create_check_constraint("training_mode", "training_run", "launch_mode IN ('practice','independent') AND (origin_id IS NULL OR origin_id <> id)")
    op.create_table("independent_work",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("training_run.id"), primary_key=True),
        sa.Column("candidate", sa.JSON()), sa.Column("history", sa.JSON(), nullable=False), sa.Column("novelty", sa.JSON()))
    op.create_table("independent_observation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("training_run.id"), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("frozen_sequence", sa.BigInteger(), nullable=False),
        sa.Column("original_id", sa.Uuid(), nullable=False),
        sa.Column("case_digest", sa.String(), nullable=False),
        sa.Column("target", sa.JSON(), nullable=False), sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("rule_version", sa.String(), nullable=False), sa.Column("semantic_reliability", sa.String(), nullable=False),
        sa.UniqueConstraint("run_id", "sequence"))
    op.create_index("ix_independent_observation_run_id", "independent_observation", ["run_id"])
    op.create_table("help_confirmation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("training_run.id"), nullable=False),
        sa.Column("help_id", sa.Uuid(), sa.ForeignKey("concept_help.id"), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False), sa.Column("direction", sa.String(), nullable=False))
    op.create_index("ix_help_confirmation_run_id", "help_confirmation", ["run_id"])
    op.execute("""CREATE FUNCTION independent_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'independent facts are immutable'; END $$""")
    for table in ("independent_observation", "help_confirmation"):
        op.execute(f"CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION independent_immutable()")
    op.execute("""CREATE FUNCTION training_mode_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF NEW.launch_mode IS DISTINCT FROM OLD.launch_mode OR NEW.origin_id IS DISTINCT FROM OLD.origin_id
         OR (OLD.converted_sequence IS NOT NULL AND NEW.converted_sequence IS DISTINCT FROM OLD.converted_sequence)
      THEN RAISE EXCEPTION 'round mode identity is immutable'; END IF;
      RETURN NEW; END $$""")
    op.execute("CREATE TRIGGER training_mode_immutable BEFORE UPDATE ON training_run FOR EACH ROW EXECUTE FUNCTION training_mode_immutable()")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM training_run WHERE launch_mode='independent')")).scalar():
        raise RuntimeError("retain independent round facts")
    op.execute("DROP TRIGGER training_mode_immutable ON training_run")
    op.execute("DROP FUNCTION training_mode_immutable()")
    op.drop_table("help_confirmation")
    op.drop_table("independent_observation")
    op.drop_table("independent_work")
    op.execute("DROP FUNCTION independent_immutable()")
    op.drop_constraint("training_mode", "training_run")
    for column in ("converted_sequence", "origin_id", "launch_mode"):
        op.drop_column("training_run", column)
