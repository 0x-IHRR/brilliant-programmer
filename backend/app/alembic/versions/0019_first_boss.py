"""First-stage Boss launch and one-step promotion facts; preserve all old rounds."""

from alembic import op
import sqlalchemy as sa

revision = "0019_first_boss"
down_revision = "0018_random_recommendations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "boss_attempt",
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("training_run.id"), primary_key=True
        ),
        sa.Column("stage", sa.JSON(), nullable=False),
        sa.Column("launch_points", sa.Integer(), nullable=False),
        sa.Column("launch_level", sa.String(), nullable=False),
    )
    op.create_table(
        "boss_promotion",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("boss_attempt.run_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "original_id",
            sa.Uuid(),
            sa.ForeignKey("training_submission.id"),
            nullable=False,
        ),
        sa.Column("frozen_sequence", sa.Integer(), nullable=False),
        sa.Column("stage_version", sa.String(), nullable=False),
        sa.Column("from_level", sa.String(), nullable=False),
        sa.Column("to_level", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "from_level"),
    )
    op.execute("""CREATE FUNCTION boss_fact_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'boss facts are immutable'; END $$""")
    for table in ["boss_attempt", "boss_promotion"]:
        op.execute(
            f"CREATE TRIGGER boss_fact_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION boss_fact_immutable()"
        )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM boss_attempt)"))
        .scalar()
    ):
        raise RuntimeError("retain existing Boss facts")
    op.drop_table("boss_promotion")
    op.drop_table("boss_attempt")
    op.execute("DROP FUNCTION boss_fact_immutable()")
