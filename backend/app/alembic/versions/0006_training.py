"""First training, persistent attempt budget and Procrastinate 3.9.0 schema."""

from alembic import op
import sqlalchemy as sa
from procrastinate.schema import SchemaManager
from importlib.metadata import version

revision = "0006_training"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    # The dependency is pinned; do not silently install a different historical schema.
    if version("procrastinate") != "3.9.0":
        raise RuntimeError("0006 requires the pinned Procrastinate 3.9.0 schema")
    bind = op.get_bind()
    if not bind.exec_driver_sql("SELECT to_regclass('procrastinate_jobs')").scalar():
        bind.connection.driver_connection.execute(SchemaManager.get_schema())
    op.create_table(
        "training_run",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("config_version", sa.Uuid(), nullable=False),
        sa.Column("destination", sa.String(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("queue_job_id", sa.BigInteger()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("stop_requested", sa.Boolean(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("generation_attempts", sa.Integer(), nullable=False),
        sa.Column("selection", sa.JSON(), nullable=False),
        sa.Column("target", sa.JSON(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("candidate", sa.JSON()),
        sa.Column("scenario_hash", sa.String()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("formal_submitted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("attempts >= 0 AND attempts <= 6"),
        sa.CheckConstraint("generation IN (0, 1) AND generation_attempts BETWEEN 0 AND 3"),
    )
    op.create_index("ix_training_run_user_id", "training_run", ["user_id"])
    op.create_table(
        "training_attempt",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("training_run.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("prompt_tokens", sa.BigInteger()),
        sa.Column("completion_tokens", sa.BigInteger()),
        sa.Column("total_tokens", sa.BigInteger()),
        sa.UniqueConstraint("run_id", "number"),
    )
    op.create_index("ix_training_attempt_run_id", "training_attempt", ["run_id"])


def downgrade():
    op.drop_table("training_attempt")
    op.drop_table("training_run")
    # Keep the queue's durable job/audit history. Library schema lifecycle is independent.
