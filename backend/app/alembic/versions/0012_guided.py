"""Guided help and independently recorded practice in the existing round."""

from alembic import op
import sqlalchemy as sa

revision = "0012_guided"
down_revision = "0011_draft"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "concept_help",
        sa.Column("kind", sa.String(), nullable=False, server_default="concept"),
    )
    op.create_check_constraint(
        "help_kind", "concept_help", "kind IN ('concept','hint','demonstration')"
    )
    op.add_column(
        "training_submission",
        sa.Column("practice_help_id", sa.Uuid(), sa.ForeignKey("concept_help.id")),
    )
    op.add_column("training_submission", sa.Column("practice_judgment_id", sa.String()))
    # 0007's unnamed original-lineage constraint gets its actual PG name.
    for (name,) in (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT conname FROM pg_constraint WHERE conrelid='training_submission'::regclass AND contype='c' AND pg_get_constraintdef(oid) LIKE '%original_id%'"
            )
        )
        .all()
    ):
        op.drop_constraint(name, "training_submission", type_="check")
    op.create_check_constraint(
        "submission_lineage",
        "training_submission",
        "(kind = 'original' AND original_id IS NULL) OR (kind IN ('clarification','supplement') AND original_id IS NOT NULL) OR kind='practice'",
    )
    op.create_check_constraint(
        "submission_practice_scope",
        "training_submission",
        "(kind='practice' AND practice_help_id IS NOT NULL AND practice_judgment_id IS NOT NULL AND NOT evaluate_after_submit) OR (kind<>'practice' AND practice_help_id IS NULL AND practice_judgment_id IS NULL)",
    )
    op.drop_index("one_neutral_clarification_per_run", table_name="training_submission")
    op.create_index(
        "one_neutral_clarification_per_run",
        "training_submission",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("neutral_clarification AND practice_help_id IS NULL"),
    )
    op.create_index(
        "one_practice_clarification",
        "training_submission",
        ["run_id", "practice_judgment_id"],
        unique=True,
        postgresql_where=sa.text(
            "neutral_clarification AND practice_help_id IS NOT NULL"
        ),
    )
    op.execute("""CREATE FUNCTION protect_guided_scope() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_TABLE_NAME='concept_help' THEN
        IF NEW.kind IS DISTINCT FROM OLD.kind THEN RAISE EXCEPTION 'immutable help kind'; END IF;
      ELSE
        IF ROW(NEW.practice_help_id,NEW.practice_judgment_id) IS DISTINCT FROM ROW(OLD.practice_help_id,OLD.practice_judgment_id) THEN RAISE EXCEPTION 'immutable practice scope'; END IF;
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER immutable_help_kind BEFORE UPDATE ON concept_help FOR EACH ROW EXECUTE FUNCTION protect_guided_scope()"
    )
    op.execute(
        "CREATE TRIGGER immutable_practice_scope BEFORE UPDATE ON training_submission FOR EACH ROW EXECUTE FUNCTION protect_guided_scope()"
    )
    op.create_table(
        "practice_draft",
        sa.Column(
            "help_id", sa.Uuid(), sa.ForeignKey("concept_help.id"), primary_key=True
        ),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("training_run.id"), nullable=False
        ),
        sa.Column("version", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("progress", sa.JSON(), nullable=False),
    )


def downgrade():
    # Existing guided facts must not be silently deleted by schema downgrade.
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM concept_help WHERE kind<>'concept')")
        )
        .scalar()
    ):
        raise RuntimeError(
            "guided facts exist; downgrade requires an explicit retention plan"
        )
    op.drop_table("practice_draft")
    op.execute("DROP TRIGGER immutable_help_kind ON concept_help")
    op.execute("DROP TRIGGER immutable_practice_scope ON training_submission")
    op.execute("DROP FUNCTION protect_guided_scope()")
    op.drop_index("one_practice_clarification", table_name="training_submission")
    op.drop_index("one_neutral_clarification_per_run", table_name="training_submission")
    op.create_index(
        "one_neutral_clarification_per_run",
        "training_submission",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("neutral_clarification"),
    )
    op.drop_constraint("submission_practice_scope", "training_submission")
    op.drop_constraint("submission_lineage", "training_submission")
    op.create_check_constraint(
        "submission_lineage",
        "training_submission",
        "(kind = 'original' AND original_id IS NULL) OR (kind IN ('clarification','supplement') AND original_id IS NOT NULL)",
    )
    op.drop_column("training_submission", "practice_help_id")
    op.drop_column("training_submission", "practice_judgment_id")
    op.drop_column("concept_help", "kind")
