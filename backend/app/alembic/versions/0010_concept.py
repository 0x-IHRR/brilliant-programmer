"""Private concepts and immutable delivery evidence."""

from alembic import op
import sqlalchemy as sa

revision = "0010_concept"
down_revision = "0009_evaluation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "concept_help",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("training_run.id"), nullable=False
        ),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("concept_help.id")),
        sa.Column("created_sequence", sa.BigInteger(), nullable=False),
        sa.Column("generated_sequence", sa.BigInteger()),
        sa.Column("checked_sequence", sa.BigInteger()),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("config_version", sa.Uuid(), nullable=False),
        sa.Column("destination", sa.String(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("content", sa.JSON()),
        sa.Column("inspection", sa.JSON()),
        sa.Column("direction", sa.String()),
        sa.Column("stop_requested", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("stage_attempts", sa.Integer(), nullable=False),
        sa.Column("attempt_limit", sa.Integer(), nullable=False),
        sa.Column("queue_job_id", sa.BigInteger()),
        sa.CheckConstraint(
            "attempts BETWEEN 0 AND 6 AND stage_attempts BETWEEN 0 AND 6 AND attempt_limit BETWEEN 1 AND 6"
        ),
    )
    op.create_index("ix_concept_help_run_id", "concept_help", ["run_id"])
    op.create_table(
        "concept_attempt",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "help_id", sa.Uuid(), sa.ForeignKey("concept_help.id"), nullable=False
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("prompt_tokens", sa.BigInteger()),
        sa.Column("completion_tokens", sa.BigInteger()),
        sa.Column("total_tokens", sa.BigInteger()),
        sa.UniqueConstraint("help_id", "number"),
    )
    op.create_index("ix_concept_attempt_help_id", "concept_attempt", ["help_id"])
    op.create_table(
        "help_delivery",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "help_id", sa.Uuid(), sa.ForeignKey("concept_help.id"), nullable=False
        ),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("training_run.id"), nullable=False
        ),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("exposure_sequence", sa.BigInteger(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), sa.ForeignKey("help_delivery.id")),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("delivered_text", sa.Text(), nullable=False),
        sa.Column("direction", sa.String()),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("receipt_hash", sa.String()),
        sa.Column("evidence", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "sequence"),
        sa.UniqueConstraint("attempt_id"),
        sa.CheckConstraint(
            "sequence > 0 AND exposure_sequence > 0 AND exposure_sequence <= sequence"
        ),
    )
    op.create_index("ix_help_delivery_help_id", "help_delivery", ["help_id"])
    op.create_index("ix_help_delivery_run_id", "help_delivery", ["run_id"])
    op.execute("""CREATE FUNCTION protect_concept_input() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF ROW(NEW.id,NEW.run_id,NEW.parent_id,NEW.created_sequence,NEW.request::text,NEW.config_version,NEW.destination,NEW.model_id)
        IS DISTINCT FROM ROW(OLD.id,OLD.run_id,OLD.parent_id,OLD.created_sequence,OLD.request::text,OLD.config_version,OLD.destination,OLD.model_id)
        OR (OLD.content IS NOT NULL AND ROW(NEW.content::text,NEW.generated_sequence) IS DISTINCT FROM ROW(OLD.content::text,OLD.generated_sequence))
        OR (OLD.inspection IS NOT NULL AND ROW(NEW.inspection::text,NEW.direction,NEW.checked_sequence) IS DISTINCT FROM ROW(OLD.inspection::text,OLD.direction,OLD.checked_sequence))
      THEN RAISE EXCEPTION 'immutable concept input or checked content'; END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER immutable_concept BEFORE UPDATE ON concept_help FOR EACH ROW EXECUTE FUNCTION protect_concept_input()"
    )
    op.execute("""CREATE FUNCTION protect_help_delivery() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'immutable help delivery observation'; END $$""")
    op.execute(
        "CREATE TRIGGER immutable_help_delivery BEFORE UPDATE ON help_delivery FOR EACH ROW EXECUTE FUNCTION protect_help_delivery()"
    )


def downgrade():
    op.drop_table("help_delivery")
    op.execute("DROP FUNCTION protect_help_delivery()")
    op.drop_table("concept_attempt")
    op.drop_table("concept_help")
    op.execute("DROP FUNCTION protect_concept_input()")
