"""Frozen evaluation inputs and round-local event ordering."""
from alembic import op
import sqlalchemy as sa

revision = "0009_evaluation"
down_revision = "0008_project"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("training_submission", sa.Column("evaluate_after_submit", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("""CREATE FUNCTION protect_evaluation_consent() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.evaluate_after_submit IS DISTINCT FROM OLD.evaluate_after_submit
      THEN RAISE EXCEPTION 'immutable evaluation consent'; END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER immutable_evaluation_consent BEFORE UPDATE ON training_submission FOR EACH ROW EXECUTE FUNCTION protect_evaluation_consent()")
    op.add_column("training_run", sa.Column("event_sequence", sa.BigInteger(), nullable=False, server_default="0"))
    op.execute("UPDATE training_run r SET event_sequence = COALESCE((SELECT MAX(s.sequence) FROM training_submission s WHERE s.run_id = r.id), 0)")
    op.drop_constraint("training_submission_sequence_key", "training_submission", type_="unique")
    op.create_unique_constraint("submission_run_sequence", "training_submission", ["run_id", "sequence"])
    op.create_table("training_evaluation",
        sa.Column("run_id",sa.Uuid(),sa.ForeignKey("training_run.id"),primary_key=True),
        sa.Column("inputs",sa.JSON(),nullable=False),
        sa.Column("case_snapshot",sa.JSON(),nullable=False),
        sa.Column("sources",sa.JSON(),nullable=False),
        sa.Column("rule_version",sa.String(),nullable=False),
        sa.Column("config_version",sa.Uuid(),nullable=False),
        sa.Column("destination",sa.String(),nullable=False),
        sa.Column("model_id",sa.String(),nullable=False),
        sa.Column("status",sa.String(),nullable=False),
        sa.Column("code",sa.String(),nullable=False),
        sa.Column("message",sa.String(),nullable=False),
        sa.Column("clarification_requested",sa.Boolean(),nullable=False),
        sa.Column("frozen_sequence",sa.BigInteger()),
        sa.Column("frozen_at",sa.DateTime(timezone=True)),
        sa.Column("result",sa.JSON()),
        sa.Column("attempts",sa.Integer(),nullable=False),
        sa.Column("attempt_limit",sa.Integer(),nullable=False),
        sa.Column("stop_requested",sa.Boolean(),nullable=False),
        sa.Column("queue_job_id",sa.BigInteger()),
        sa.CheckConstraint("attempts BETWEEN 0 AND 6 AND attempt_limit BETWEEN 1 AND 6"))
    op.create_table("evaluation_attempt",
        sa.Column("id",sa.Uuid(),primary_key=True),
        sa.Column("run_id",sa.Uuid(),sa.ForeignKey("training_evaluation.run_id"),nullable=False),
        sa.Column("number",sa.Integer(),nullable=False),
        sa.Column("code",sa.String(),nullable=False),
        sa.Column("prompt_tokens",sa.BigInteger()),
        sa.Column("completion_tokens",sa.BigInteger()),
        sa.Column("total_tokens",sa.BigInteger()),
        sa.UniqueConstraint("run_id","number"))
    op.create_index("ix_evaluation_attempt_run_id", "evaluation_attempt", ["run_id"])
    op.execute("""CREATE FUNCTION protect_evaluation_input() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF ROW(NEW.run_id,NEW.case_snapshot::text,NEW.sources::text,NEW.rule_version,NEW.config_version,NEW.destination,NEW.model_id)
         IS DISTINCT FROM ROW(OLD.run_id,OLD.case_snapshot::text,OLD.sources::text,OLD.rule_version,OLD.config_version,OLD.destination,OLD.model_id)
         OR (OLD.frozen_sequence IS NOT NULL AND ROW(NEW.inputs::text,NEW.frozen_sequence,NEW.frozen_at)
             IS DISTINCT FROM ROW(OLD.inputs::text,OLD.frozen_sequence,OLD.frozen_at))
      THEN RAISE EXCEPTION 'immutable evaluation input'; END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER immutable_evaluation BEFORE UPDATE ON training_evaluation FOR EACH ROW EXECUTE FUNCTION protect_evaluation_input()")


def downgrade():
    op.execute("DROP TRIGGER immutable_evaluation_consent ON training_submission")
    op.execute("DROP FUNCTION protect_evaluation_consent()")
    op.drop_column("training_submission", "evaluate_after_submit")
    op.execute("DROP TRIGGER immutable_evaluation ON training_evaluation")
    op.execute("DROP FUNCTION protect_evaluation_input()")
    op.drop_table("evaluation_attempt")
    op.drop_table("training_evaluation")
    # Fail transactionally if used per-round values cannot regain the old global uniqueness.
    op.drop_constraint("submission_run_sequence", "training_submission", type_="unique")
    op.create_unique_constraint("training_submission_sequence_key", "training_submission", ["sequence"])
    op.drop_column("training_run", "event_sequence")
