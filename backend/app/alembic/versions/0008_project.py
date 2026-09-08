"""Independent fixed-version project tasks, checkpoints and provider attempts."""
from alembic import op
import sqlalchemy as sa

revision = "0008_project"
down_revision = "0007_submission"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("project_run",
        sa.Column("id",sa.Uuid(),primary_key=True),
        sa.Column("user_id",sa.Uuid(),sa.ForeignKey("user.id"),nullable=False),
        sa.Column("url",sa.String(),nullable=False),
        sa.Column("reanalyze",sa.Boolean(),nullable=False),
        sa.Column("config_version",sa.Uuid(),nullable=False),
        sa.Column("destination",sa.String(),nullable=False),
        sa.Column("model_id",sa.String(),nullable=False),
        sa.Column("queue_job_id",sa.BigInteger()),
        sa.Column("reused_from_id",sa.Uuid(),sa.ForeignKey("project_run.id")),
        sa.Column("repository_key",sa.String()),
        sa.Column("commit",sa.String()),
        sa.Column("status",sa.String(),nullable=False),
        sa.Column("code",sa.String(),nullable=False),
        sa.Column("message",sa.String(),nullable=False),
        sa.Column("stop_requested",sa.Boolean(),nullable=False),
        sa.Column("acquisition_done",sa.Boolean(),nullable=False),
        sa.Column("source_requests",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("source_bytes",sa.BigInteger(),nullable=False,server_default="0"),
        sa.Column("attempts",sa.Integer(),nullable=False),
        sa.Column("generation",sa.Integer(),nullable=False),
        sa.Column("generation_attempts",sa.Integer(),nullable=False),
        sa.Column("snapshot",sa.JSON()),
        sa.Column("project_map",sa.JSON()),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("attempts BETWEEN 0 AND 6 AND generation BETWEEN 0 AND 1 AND generation_attempts BETWEEN 0 AND 3"),
        sa.CheckConstraint("status IN ('queued','running','completed','failed','stopping','stopped')"))
    for name in ("user_id","repository_key","commit"):
        op.create_index("ix_project_run_"+name,"project_run",[name])
    op.create_table("project_attempt",
        sa.Column("id",sa.Uuid(),primary_key=True),
        sa.Column("run_id",sa.Uuid(),sa.ForeignKey("project_run.id"),nullable=False),
        sa.Column("number",sa.Integer(),nullable=False),
        sa.Column("generation",sa.Integer(),nullable=False),
        sa.Column("code",sa.String(),nullable=False),
        sa.Column("prompt_tokens",sa.BigInteger()),
        sa.Column("completion_tokens",sa.BigInteger()),
        sa.Column("total_tokens",sa.BigInteger()),
        sa.UniqueConstraint("run_id","number"))
    op.create_index("ix_project_attempt_run_id","project_attempt",["run_id"])


def downgrade():
    op.drop_table("project_attempt")
    op.drop_table("project_run")
