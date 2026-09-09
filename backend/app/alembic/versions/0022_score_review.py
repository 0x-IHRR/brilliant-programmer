"""One frozen review per evaluation, immutable per-call destinations and top-ups."""

from alembic import op
import sqlalchemy as sa

revision = "0022_score_review"
down_revision = "0021_boss_stages"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "score_review",
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("training_evaluation.run_id"),
            primary_key=True,
        ),
        sa.Column("request_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("opinion", sa.JSON()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("config_version", sa.Uuid(), nullable=False),
        sa.Column("destination", sa.String(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("queue_job_id", sa.BigInteger()),
        sa.Column("stop_requested", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("attempt_limit", sa.Integer(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "review_attempt",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("score_review.run_id"), nullable=False
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("config_version", sa.Uuid(), nullable=False),
        sa.Column("destination", sa.String(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("prompt_tokens", sa.BigInteger()),
        sa.Column("completion_tokens", sa.BigInteger()),
        sa.Column("total_tokens", sa.BigInteger()),
        sa.UniqueConstraint("run_id", "number"),
    )
    op.create_index("ix_review_attempt_run_id", "review_attempt", ["run_id"])
    op.create_table(
        "review_award",
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("score_review.run_id"), primary_key=True
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("rule_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("points > 0"),
    )
    op.create_index("ix_review_award_user_id", "review_award", ["user_id"])
    op.execute("""CREATE FUNCTION protect_score_review() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'review acceptance is immutable'; END IF;
      IF NEW.run_id<>OLD.run_id OR NEW.request_id<>OLD.request_id OR
         NEW.snapshot::jsonb<>OLD.snapshot::jsonb OR NEW.accepted_at<>OLD.accepted_at THEN
        RAISE EXCEPTION 'review snapshot is immutable';
      END IF;
      IF OLD.decision <> 'pending' AND (NEW.decision<>OLD.decision OR NEW.opinion::jsonb IS DISTINCT FROM OLD.opinion::jsonb) THEN
        RAISE EXCEPTION 'review conclusion is immutable';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER score_review_immutable BEFORE UPDATE OR DELETE ON score_review FOR EACH ROW EXECUTE FUNCTION protect_score_review()"
    )
    op.execute("""CREATE FUNCTION protect_review_call() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'review call identity is immutable'; END IF;
      IF ROW(NEW.id,NEW.run_id,NEW.number,NEW.config_version,NEW.destination,NEW.model_id) IS DISTINCT FROM
         ROW(OLD.id,OLD.run_id,OLD.number,OLD.config_version,OLD.destination,OLD.model_id) THEN
        RAISE EXCEPTION 'review call identity is immutable';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER review_call_immutable BEFORE UPDATE OR DELETE ON review_attempt FOR EACH ROW EXECUTE FUNCTION protect_review_call()"
    )
    op.execute("""CREATE FUNCTION protect_review_award() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'review award is immutable'; END $$""")
    op.execute(
        "CREATE TRIGGER review_award_immutable BEFORE UPDATE OR DELETE ON review_award FOR EACH ROW EXECUTE FUNCTION protect_review_award()"
    )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM score_review)"))
        .scalar()
    ):
        raise RuntimeError("retain accepted review and accounting facts")
    for table in ("review_award", "review_attempt", "score_review"):
        op.drop_table(table)
    for function in (
        "protect_review_award",
        "protect_review_call",
        "protect_score_review",
    ):
        op.execute("DROP FUNCTION " + function + "()")
