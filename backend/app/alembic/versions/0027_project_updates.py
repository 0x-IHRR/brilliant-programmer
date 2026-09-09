"""Link updated project routes without rewriting their original provenance."""

from alembic import op
import sqlalchemy as sa

revision = "0027_project_updates"
down_revision = "0026_project_training"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "project_training_input",
        sa.Column(
            "previous_version_id",
            sa.Uuid(),
            sa.ForeignKey("topic_version.id"),
            nullable=True,
        ),
    )
    op.create_table(
        "project_route_family",
        sa.Column(
            "root_topic_id", sa.Uuid(), sa.ForeignKey("topic.id"), primary_key=True
        ),
        sa.Column("active_version_id", sa.Uuid(), sa.ForeignKey("topic_version.id")),
    )
    op.create_table(
        "project_route_update",
        sa.Column("topic_id", sa.Uuid(), sa.ForeignKey("topic.id"), primary_key=True),
        sa.Column(
            "root_topic_id",
            sa.Uuid(),
            sa.ForeignKey("project_route_family.root_topic_id"),
            nullable=False,
        ),
        sa.Column(
            "previous_version_id",
            sa.Uuid(),
            sa.ForeignKey("project_training_version.version_id"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_project_route_update_root_topic_id",
        "project_route_update",
        ["root_topic_id"],
    )
    op.execute(
        "CREATE TRIGGER project_update_immutable BEFORE UPDATE OR DELETE ON project_route_update FOR EACH ROW EXECUTE FUNCTION topic_snapshot_immutable()"
    )
    op.execute("""INSERT INTO project_route_family(root_topic_id,active_version_id)
        SELECT t.id,t.active_id FROM topic t JOIN project_topic p ON p.topic_id=t.id""")


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM project_route_update)"))
        .scalar()
    ):
        raise RuntimeError("retain project update lineage")
    op.drop_table("project_route_update")
    op.drop_table("project_route_family")
    op.drop_column("project_training_input", "previous_version_id")
