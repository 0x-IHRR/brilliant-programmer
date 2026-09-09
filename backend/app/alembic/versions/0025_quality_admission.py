"""Version-bound reports and immutable admission decisions; no model evaluation."""
from alembic import op
import sqlalchemy as sa

revision = "0025_quality_admission"
down_revision = "0024_jd_route"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("quality_evidence",
        sa.Column("sha256", sa.String(), primary_key=True),
        sa.Column("content", sa.LargeBinary(), nullable=False))
    op.create_table("quality_report",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("artifact_sha256", sa.String(), nullable=False, unique=True),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "sequence"))
    op.create_index("ix_quality_report_user_id", "quality_report", ["user_id"])
    op.create_table("quality_disposition",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("training_run.id"), primary_key=True),
        sa.Column("phase", sa.String(), primary_key=True),
        sa.Column("report_id", sa.Uuid(), sa.ForeignKey("quality_report.id")),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("binding", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    # Do not reinterpret historical observations using future imported reports.
    # Their true actual scoring configuration is retained; quality remains unknown.
    op.execute('''INSERT INTO quality_disposition(run_id, phase, status, binding, created_at)
        SELECT e.run_id, 'original', 'unverified', json_build_object(
            'user_id', r.user_id, 'config_version', e.config_version,
            'destination', e.destination, 'model_id', e.model_id,
            'evaluation_rule', e.rule_version), CURRENT_TIMESTAMP
        FROM training_evaluation e JOIN training_run r ON r.id=e.run_id
        WHERE EXISTS(SELECT 1 FROM independent_observation o WHERE o.run_id=e.run_id AND o.outcome <> 'pending_delivery')''')
    op.execute('''INSERT INTO quality_disposition(run_id, phase, status, binding, created_at)
        SELECT s.run_id, 'review', 'unverified', json_build_object(
            'user_id', r.user_id, 'config_version', s.config_version,
            'destination', s.destination, 'model_id', s.model_id,
            'evaluation_rule', e.rule_version), CURRENT_TIMESTAMP
        FROM score_review s JOIN training_run r ON r.id=s.run_id
        JOIN training_evaluation e ON e.run_id=s.run_id WHERE s.status='completed' ''')
    for table in ("quality_report", "quality_disposition", "quality_evidence"):
        op.execute(f"CREATE TRIGGER quality_fact_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION boss_fact_immutable()")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM quality_report)")).scalar():
        raise RuntimeError("retain imported quality evidence")
    op.drop_table("quality_disposition")
    op.drop_table("quality_report")
    op.drop_table("quality_evidence")
