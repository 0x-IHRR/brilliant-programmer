"""Explicit preference and first-publication facts; no guessed legacy counts."""

from alembic import op
import sqlalchemy as sa

revision = "0018_random_recommendations"
down_revision = "0017_prerequisite_unlocks"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "random_preference",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), primary_key=True),
        sa.Column("version", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.CheckConstraint("mode IN ('recommended','基础','进阶','综合')"),
    )
    op.add_column(
        "training_run",
        sa.Column("recommendation_delivered_at", sa.DateTime(timezone=True)),
    )
    # Legacy random selection was explicitly first-round-only, never the new
    # post-formal-answer recommendation mode. Keep its data; do not invent count.
    op.execute("""CREATE FUNCTION recommendation_fact_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.recommendation_delivered_at IS NOT NULL AND NEW.recommendation_delivered_at IS DISTINCT FROM OLD.recommendation_delivered_at THEN RAISE EXCEPTION 'publication fact immutable'; END IF;
      IF NEW.recommendation_delivered_at IS NOT NULL AND (NEW.candidate IS NULL OR NEW.selection->>'random_mode' IS DISTINCT FROM 'recommended') THEN RAISE EXCEPTION 'not a recommended publication'; END IF;
      IF OLD.selection->>'entry'='random' AND (NEW.selection::jsonb IS DISTINCT FROM OLD.selection::jsonb OR NEW.target::jsonb IS DISTINCT FROM OLD.target::jsonb) THEN RAISE EXCEPTION 'random selection immutable'; END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER recommendation_fact_immutable BEFORE UPDATE ON training_run FOR EACH ROW EXECUTE FUNCTION recommendation_fact_immutable()"
    )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM random_preference) OR EXISTS(SELECT 1 FROM training_run WHERE recommendation_delivered_at IS NOT NULL)"
            )
        )
        .scalar()
    ):
        raise RuntimeError("retain random preference and publication facts")
    op.execute("DROP TRIGGER recommendation_fact_immutable ON training_run")
    op.execute("DROP FUNCTION recommendation_fact_immutable()")
    op.drop_column("training_run", "recommendation_delivered_at")
    op.drop_table("random_preference")
