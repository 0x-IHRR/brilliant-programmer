"""Immutable submission inputs and atomic per-round practice award."""
from alembic import op
import sqlalchemy as sa

revision = "0007_submission"
down_revision = "0006_training"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("training_run", sa.Column("completion_rule_version", sa.String(), nullable=False, server_default="completion-v1.0"))
    op.create_table(
        "training_submission",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("training_run.id"), nullable=False),
        sa.Column("original_id", sa.Uuid(), sa.ForeignKey("training_submission.id")),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(), nullable=False),
        sa.Column("config_version", sa.Uuid(), nullable=False),
        sa.Column("destination", sa.String(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stop_requested", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("relevance", sa.JSON(), nullable=False),
        sa.Column("neutral_clarification", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("attempt_limit", sa.Integer(), nullable=False),
        sa.Column("queue_job_id", sa.BigInteger()),
        sa.UniqueConstraint("run_id", "input_hash"),
        sa.CheckConstraint("attempts BETWEEN 0 AND 6 AND attempt_limit BETWEEN 1 AND 6"),
        sa.CheckConstraint("(kind = 'original' AND original_id IS NULL) OR (kind IN ('clarification', 'supplement') AND original_id IS NOT NULL)"),
        sa.CheckConstraint("status IN ('checking', 'needs_supplement', 'failed', 'completed', 'stopping', 'stopped')"),
    )
    op.create_index("ix_training_submission_run_id", "training_submission", ["run_id"])
    op.create_index("one_original_per_run", "training_submission", ["run_id"], unique=True, postgresql_where=sa.text("kind = 'original'"))
    op.create_index("one_neutral_clarification_per_run", "training_submission", ["run_id"], unique=True, postgresql_where=sa.text("neutral_clarification"))
    op.create_index("one_clarification_answer_per_run", "training_submission", ["run_id"], unique=True, postgresql_where=sa.text("kind = 'clarification'"))
    op.create_table(
        "submission_attempt",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("submission_id", sa.Uuid(), sa.ForeignKey("training_submission.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("prompt_tokens", sa.BigInteger()),
        sa.Column("completion_tokens", sa.BigInteger()),
        sa.Column("total_tokens", sa.BigInteger()),
        sa.UniqueConstraint("submission_id", "number"),
    )
    op.create_index("ix_submission_attempt_submission_id", "submission_attempt", ["submission_id"])
    op.create_table(
        "practice_award",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("training_run.id"), primary_key=True),
        sa.Column("submission_id", sa.Uuid(), sa.ForeignKey("training_submission.id"), nullable=False, unique=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("rule_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("points = 10 AND rule_version = 'completion-v1.0'"),
    )
    op.create_index("ix_practice_award_user_id", "practice_award", ["user_id"])
    op.execute("""CREATE FUNCTION protect_submission_input() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF ROW(NEW.id, NEW.sequence, NEW.run_id, NEW.original_id, NEW.kind, NEW.answers::text,
             NEW.input_hash, NEW.config_version, NEW.destination, NEW.model_id, NEW.created_at)
         IS DISTINCT FROM ROW(OLD.id, OLD.sequence, OLD.run_id, OLD.original_id, OLD.kind,
             OLD.answers::text, OLD.input_hash, OLD.config_version, OLD.destination, OLD.model_id, OLD.created_at)
      THEN RAISE EXCEPTION 'immutable submission input'; END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER immutable_submission BEFORE UPDATE ON training_submission FOR EACH ROW EXECUTE FUNCTION protect_submission_input()")
    op.execute("""CREATE FUNCTION protect_formal_submission_time() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.completion_rule_version IS DISTINCT FROM OLD.completion_rule_version
         OR (OLD.formal_submitted_at IS NOT NULL AND NEW.formal_submitted_at IS DISTINCT FROM OLD.formal_submitted_at)
      THEN RAISE EXCEPTION 'immutable formal submission time'; END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER immutable_formal_time BEFORE UPDATE ON training_run FOR EACH ROW EXECUTE FUNCTION protect_formal_submission_time()")


def downgrade():
    op.execute("DROP TRIGGER immutable_formal_time ON training_run")
    op.execute("DROP FUNCTION protect_formal_submission_time()")
    op.execute("DROP TRIGGER immutable_submission ON training_submission")
    op.execute("DROP FUNCTION protect_submission_input()")
    op.drop_table("practice_award")
    op.drop_table("submission_attempt")
    op.drop_table("training_submission")
    op.drop_column("training_run", "completion_rule_version")
