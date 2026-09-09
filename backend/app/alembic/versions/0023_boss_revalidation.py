"""Append-only per-promotion revalidation and frozen round disposition."""

from alembic import op
import sqlalchemy as sa

revision = "0023_boss_revalidation"
down_revision = "0022_score_review"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "boss_revalidation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("promotion_id", sa.Uuid(), sa.ForeignKey("boss_promotion.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("review_run_id", sa.Uuid(), sa.ForeignKey("score_review.run_id"), unique=True),
        sa.Column("resolved_run_id", sa.Uuid(), sa.ForeignKey("boss_attempt.run_id"), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("promotion_id", "sequence"),
        sa.CheckConstraint("sequence > 0 AND ((kind = 'required' AND review_run_id IS NOT NULL AND resolved_run_id IS NULL) OR (kind = 'resolved' AND review_run_id IS NULL AND resolved_run_id IS NOT NULL))", name="revalidation_event_shape"),
    )
    op.add_column("boss_attempt", sa.Column("revalidation_of", sa.Uuid(), sa.ForeignKey("boss_promotion.id", name="boss_attempt_revalidation_of_fkey")))
    op.add_column("boss_attempt", sa.Column("revalidation_event_id", sa.Uuid(), sa.ForeignKey("boss_revalidation.id", name="boss_attempt_revalidation_event_id_fkey")))
    op.add_column("boss_attempt", sa.Column("promotion_blocked", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "boss_disposition",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("boss_attempt.run_id"), primary_key=True),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for table in ("boss_revalidation", "boss_disposition"):
        op.execute(f"CREATE TRIGGER boss_fact_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION boss_fact_immutable()")

    # Preserve existing immutable facts. The pure frozen-result validator checks
    # every source, original/clarification and Boss facet; no network or level write.
    from sqlmodel import Session, select
    from app.models import User
    from app.training.boss_models import BossPromotion
    from app.training.boss_service import mark_reviewed_promotion
    from app.training.models import TrainingRun
    from app.training.review_models import ScoreReview
    with Session(op.get_bind(), join_transaction_mode="create_savepoint") as session:
        with session.begin():
            reviews = session.exec(select(ScoreReview).join(BossPromotion, BossPromotion.run_id == ScoreReview.run_id).where(ScoreReview.status == "completed", ScoreReview.decision == "corrected")).all()
            for review in reviews:
                run = session.get(TrainingRun, review.run_id)
                session.exec(select(User).where(User.id == run.user_id).with_for_update()).one()
                mark_reviewed_promotion(session, run, review, legacy_backfill=True)
            session.flush()


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM boss_revalidation) OR EXISTS(SELECT 1 FROM boss_disposition) OR EXISTS(SELECT 1 FROM boss_attempt WHERE revalidation_of IS NOT NULL OR promotion_blocked) ")).scalar():
        raise RuntimeError("retain revalidation and frozen disposition facts")
    op.drop_table("boss_disposition")
    op.drop_column("boss_attempt", "promotion_blocked")
    op.drop_column("boss_attempt", "revalidation_event_id")
    op.drop_column("boss_attempt", "revalidation_of")
    op.drop_table("boss_revalidation")
