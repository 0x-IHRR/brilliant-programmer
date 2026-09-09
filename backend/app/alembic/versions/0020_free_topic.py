"""Topic history, confirmation pointers and bounded analysis attempts."""
from alembic import op
import sqlalchemy as sa

revision = '0020_free_topic'
down_revision = '0019_first_boss'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE topic (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	current_id UUID, 
	active_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES "user" (id)
)
    """)
    op.execute('CREATE INDEX ix_topic_user_id ON topic (user_id)')
    op.execute("""
CREATE TABLE topic_version (
	id UUID NOT NULL, 
	topic_id UUID NOT NULL, 
	snapshot JSON NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(topic_id) REFERENCES topic (id)
)
    """)
    op.execute('CREATE INDEX ix_topic_version_topic_id ON topic_version (topic_id)')
    op.execute("""
CREATE TABLE topic_job (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	topic_id UUID NOT NULL, 
	expected_version UUID, 
	input_text VARCHAR NOT NULL, 
	expand BOOLEAN NOT NULL, 
	config_version UUID NOT NULL, 
	destination VARCHAR NOT NULL, 
	model_id VARCHAR NOT NULL, 
	queue_job_id BIGINT, 
	status VARCHAR NOT NULL, 
	code VARCHAR NOT NULL, 
	message VARCHAR NOT NULL, 
	stop_requested BOOLEAN NOT NULL, 
	attempts INTEGER NOT NULL, 
	attempt_limit INTEGER NOT NULL, 
	stage VARCHAR NOT NULL, 
	candidate JSON, 
	result_id UUID, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES "user" (id), 
	FOREIGN KEY(topic_id) REFERENCES topic (id)
)
    """)
    op.execute('CREATE INDEX ix_topic_job_topic_id ON topic_job (topic_id)')
    op.execute('CREATE INDEX ix_topic_job_user_id ON topic_job (user_id)')
    op.execute("""
CREATE TABLE topic_attempt (
	id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	number INTEGER NOT NULL, 
	stage VARCHAR NOT NULL, 
	code VARCHAR NOT NULL, 
	prompt_tokens BIGINT, 
	completion_tokens BIGINT, 
	total_tokens BIGINT, 
	PRIMARY KEY (id), 
	UNIQUE (run_id, number), 
	FOREIGN KEY(run_id) REFERENCES topic_job (id)
)
    """)
    op.execute('CREATE INDEX ix_topic_attempt_run_id ON topic_attempt (run_id)')
    op.execute("""
CREATE TABLE topic_case (
	run_id UUID NOT NULL, 
	candidate JSON NOT NULL, 
	PRIMARY KEY (run_id), 
	FOREIGN KEY(run_id) REFERENCES training_run (id)
)
    """)
    op.execute("""CREATE FUNCTION topic_snapshot_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'topic snapshots are immutable'; END $$""")
    op.execute('CREATE TRIGGER topic_snapshot_immutable BEFORE UPDATE OR DELETE ON topic_version FOR EACH ROW EXECUTE FUNCTION topic_snapshot_immutable()')

    op.execute('CREATE TRIGGER topic_snapshot_immutable BEFORE UPDATE OR DELETE ON topic_case FOR EACH ROW EXECUTE FUNCTION topic_snapshot_immutable()')
    op.execute("""CREATE FUNCTION topic_goal_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.selection->>'entry' = 'free_topic' AND
        (NEW.selection::jsonb IS DISTINCT FROM OLD.selection::jsonb OR NEW.target::jsonb IS DISTINCT FROM OLD.target::jsonb)
      THEN RAISE EXCEPTION 'confirmed topic goal is immutable'; END IF;
      RETURN NEW;
    END $$""")
    op.execute('CREATE TRIGGER topic_goal_immutable BEFORE UPDATE ON training_run FOR EACH ROW EXECUTE FUNCTION topic_goal_immutable()')


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS(SELECT 1 FROM topic)')).scalar():
        raise RuntimeError('retain topic history')
    for table in ('topic_case', 'topic_attempt', 'topic_job', 'topic_version', 'topic'):
        op.drop_table(table)
    op.execute('DROP TRIGGER topic_goal_immutable ON training_run')
    op.execute('DROP FUNCTION topic_goal_immutable()')
    op.execute('DROP FUNCTION topic_snapshot_immutable()')
