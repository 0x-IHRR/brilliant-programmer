"""Account deletion intent, exact row permits and no-text restore identity."""

import json
import re

from alembic import op
import sqlalchemy as sa

revision = "0029_account_erasure"
down_revision = "0028_permanent_deletion"
branch_labels = None
depends_on = None

# Frozen actual owner-table inventory; never infer a deletion policy from new columns.
KEYS = {'boss_revalidation': ['id'], 'project_route_update': ['topic_id'], 'boss_promotion': ['id'], 'practice_award': ['run_id'], 'capability_original_order': ['original_id'], 'submission_attempt': ['id'], 'review_award': ['run_id'], 'review_attempt': ['id'], 'project_training_version': ['version_id'], 'jd_route': ['version_id'], 'jd_analysis': ['document_id'], 'practice_draft': ['help_id'], 'concept_attempt': ['id'], 'help_confirmation': ['id'], 'draft_collection': ['scope_key'], 'training_submission': ['id'], 'help_delivery': ['id'], 'evaluation_attempt': ['id'], 'score_review': ['run_id'], 'boss_disposition': ['run_id'], 'project_training_input': ['id'], 'project_route_family': ['root_topic_id'], 'topic_attempt': ['id'], 'jd_document': ['id'], 'quality_disposition': ['run_id', 'phase'], 'training_draft': ['run_id'], 'concept_help': ['id'], 'independent_observation': ['id'], 'training_attempt': ['id'], 'training_evaluation': ['run_id'], 'independent_work': ['run_id'], 'boss_attempt': ['run_id'], 'project_training_materials': ['run_id'], 'topic_case': ['run_id'], 'topic_version': ['id'], 'jd_topic': ['topic_id'], 'project_topic': ['topic_id'], 'topic_job': ['id'], 'project_attempt': ['id'], 'erased_object': ['user_id', 'kind', 'object_id'], 'erased_attachment': ['request_id', 'sha256'], 'erased_row': ['table_name', 'row_key', 'request_id'], 'quality_report': ['id'], 'training_run': ['id'], 'emailverification': ['user_id'], 'topic': ['id'], 'project_run': ['id'], 'probe_attempt': ['id'], 'archived_object': ['user_id', 'kind', 'object_id'], 'loginsession': ['id'], 'opened_unit': ['user_id', 'catalog_version', 'capability_id', 'difficulty', 'background_id'], 'random_preference': ['user_id'], 'model_config': ['user_id'], 'passwordreset': ['user_id'], 'deletion_request': ['id'], 'user': ['id']}
INJECTION = "\nIF TG_OP = 'DELETE' AND account_delete_allowed(TG_TABLE_NAME, to_jsonb(OLD)) THEN RETURN OLD; END IF;\n"
CYCLES = {("boss_attempt", "revalidation_of"), ("boss_attempt", "revalidation_event_id"), ("boss_revalidation", "resolved_run_id")}


def upgrade():
    op.create_table("account_erasure",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), unique=True, nullable=False),
        sa.Column("authentication_digest", sa.String(), nullable=False),
        sa.Column("receipt_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_table("account_journal_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identity", sa.String(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False))
    op.create_table("account_erasure_permit",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("table_name", sa.String(), primary_key=True),
        sa.Column("row_key", sa.String(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), nullable=False))
    op.execute("""CREATE FUNCTION account_row_owner(t text, r jsonb) RETURNS uuid LANGUAGE plpgsql AS $$
    DECLARE owner_id uuid; parent_id uuid;
    BEGIN
      IF t='user' THEN RETURN (r->>'id')::uuid; END IF;
      IF r ? 'user_id' THEN RETURN (r->>'user_id')::uuid; END IF;
      IF t='boss_revalidation' THEN SELECT user_id INTO owner_id FROM boss_promotion WHERE id=(r->>'promotion_id')::uuid;
      ELSIF t='erased_attachment' THEN SELECT user_id INTO owner_id FROM deletion_request WHERE id=(r->>'request_id')::uuid;
      ELSIF t='project_attempt' THEN SELECT user_id INTO owner_id FROM project_run WHERE id=(r->>'run_id')::uuid;
      ELSIF t='topic_attempt' THEN SELECT user_id INTO owner_id FROM topic_job WHERE id=(r->>'run_id')::uuid;
      ELSIF t='concept_attempt' THEN SELECT run_id INTO parent_id FROM concept_help WHERE id=(r->>'help_id')::uuid; SELECT user_id INTO owner_id FROM training_run WHERE id=parent_id;
      ELSIF t='submission_attempt' THEN SELECT run_id INTO parent_id FROM training_submission WHERE id=(r->>'submission_id')::uuid; SELECT user_id INTO owner_id FROM training_run WHERE id=parent_id;
      ELSIF t='project_route_family' THEN SELECT user_id INTO owner_id FROM topic WHERE id=(r->>'root_topic_id')::uuid;
      ELSIF r ? 'run_id' THEN SELECT user_id INTO owner_id FROM training_run WHERE id=(r->>'run_id')::uuid;
      ELSIF r ? 'topic_id' THEN SELECT user_id INTO owner_id FROM topic WHERE id=(r->>'topic_id')::uuid;
      ELSIF t='jd_analysis' THEN SELECT topic_id INTO parent_id FROM jd_document WHERE id=(r->>'document_id')::uuid; SELECT user_id INTO owner_id FROM topic WHERE id=parent_id;
      ELSIF r ? 'version_id' THEN SELECT topic_id INTO parent_id FROM topic_version WHERE id=(r->>'version_id')::uuid; SELECT user_id INTO owner_id FROM topic WHERE id=parent_id;
      END IF;
      RETURN owner_id;
    END $$""")
    policy = json.dumps(KEYS | {"quality_evidence": ["sha256"]}).replace("'", "''")
    op.execute(f"""CREATE FUNCTION account_row_key(t text, r jsonb) RETURNS text LANGUAGE sql IMMUTABLE AS $$
       SELECT jsonb_agg(r ->> k.value ORDER BY k.ordinality)::text
       FROM jsonb_array_elements_text('{policy}'::jsonb -> t) WITH ORDINALITY k(value,ordinality)
    $$""")
    op.execute("""CREATE FUNCTION account_delete_allowed(t text, r jsonb) RETURNS boolean LANGUAGE sql STABLE AS $$
       SELECT EXISTS (SELECT 1 FROM account_erasure_permit p JOIN account_erasure a ON a.user_id=p.user_id AND a.request_id=p.request_id
       WHERE p.table_name=t AND p.row_key=account_row_key(t,r) AND a.accepted_at IS NOT NULL AND a.completed_at IS NULL)
    $$""")
    op.execute("""CREATE FUNCTION account_permit_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE r jsonb; owner_id uuid;
    BEGIN
      IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'account deletion permit cannot be changed'; END IF;
      IF NOT EXISTS (SELECT 1 FROM account_erasure WHERE user_id=NEW.user_id AND request_id=NEW.request_id AND accepted_at IS NOT NULL AND completed_at IS NULL) THEN RAISE EXCEPTION 'no confirmed account erasure'; END IF;
      IF NEW.table_name='quality_evidence' THEN
        IF NOT EXISTS (SELECT 1 FROM quality_report WHERE user_id=NEW.user_id AND jsonb_path_exists(report::jsonb,'$.** ? (@ == $sha)',jsonb_build_object('sha',(NEW.row_key::jsonb)->>0))) THEN RAISE EXCEPTION 'attachment not owned'; END IF;
      ELSE
        IF account_row_key(NEW.table_name,'{}'::jsonb) IS NULL THEN RAISE EXCEPTION 'unknown account deletion table'; END IF;
        EXECUTE format('SELECT to_jsonb(t) FROM %I t WHERE account_row_key($1,to_jsonb(t))=$2',NEW.table_name) INTO r USING NEW.table_name,NEW.row_key;
        owner_id := account_row_owner(NEW.table_name,r);
        IF owner_id IS DISTINCT FROM NEW.user_id THEN RAISE EXCEPTION 'account deletion permit belongs to another owner'; END IF;
      END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER account_permit_scope BEFORE INSERT OR UPDATE ON account_erasure_permit FOR EACH ROW EXECUTE FUNCTION account_permit_guard()")
    connection=op.get_bind()
    functions=connection.execute(sa.text("""SELECT DISTINCT p.oid,pg_get_functiondef(p.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT t.tgisinternal AND n.nspname=current_schema() AND c.relname=ANY(:tables) AND (t.tgtype & 1)=1"""),{"tables":list(KEYS)+["quality_evidence"]}).all()
    for _,definition in functions:
        op.execute(re.sub(r"\bBEGIN\b",lambda m:m.group(0)+INJECTION,definition,count=1,flags=re.I))
    op.execute("""CREATE FUNCTION account_write_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE owner_id uuid;
    BEGIN
      IF TG_OP='DELETE' THEN
        IF TG_TABLE_NAME='user' AND NOT account_delete_allowed(TG_TABLE_NAME,to_jsonb(OLD)) THEN RAISE EXCEPTION 'account deletion needs confirmation'; END IF;
        RETURN OLD;
      END IF;
      IF TG_OP='UPDATE' AND TG_TABLE_NAME IN ('training_attempt','project_attempt','submission_attempt','evaluation_attempt','concept_attempt','review_attempt','topic_attempt','probe_attempt') AND (to_jsonb(NEW)-ARRAY['code','prompt_tokens','completion_tokens','total_tokens']) = (to_jsonb(OLD)-ARRAY['code','prompt_tokens','completion_tokens','total_tokens']) THEN RETURN NEW; END IF;
      owner_id := account_row_owner(TG_TABLE_NAME,to_jsonb(NEW));
      IF EXISTS (SELECT 1 FROM account_erasure WHERE user_id=owner_id AND accepted_at IS NOT NULL) THEN RAISE EXCEPTION 'erased account cannot accept new writes'; END IF;
      IF TG_OP='UPDATE' AND EXISTS (SELECT 1 FROM account_erasure WHERE user_id=account_row_owner(TG_TABLE_NAME,to_jsonb(OLD)) AND accepted_at IS NOT NULL) THEN RAISE EXCEPTION 'erased account cannot move its records'; END IF;
      RETURN NEW;
    END $$""")
    for table in KEYS:
        op.execute(f'CREATE TRIGGER aa_account_erasure BEFORE INSERT OR UPDATE OR DELETE ON "{table}" FOR EACH ROW EXECUTE FUNCTION account_write_guard()')
    op.execute("""CREATE FUNCTION account_intent_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'account erasure intent is immutable'; END IF;
      IF NEW.user_id IS DISTINCT FROM OLD.user_id OR (OLD.accepted_at IS NOT NULL AND
       ((to_jsonb(NEW)-ARRAY['authentication_digest','completed_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['authentication_digest','completed_at']) OR NEW.authentication_digest NOT IN ('',OLD.authentication_digest) OR (OLD.completed_at IS NOT NULL AND NEW.completed_at IS DISTINCT FROM OLD.completed_at))) THEN RAISE EXCEPTION 'account erasure intent is immutable'; END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER account_intent_guard BEFORE UPDATE OR DELETE ON account_erasure FOR EACH ROW EXECUTE FUNCTION account_intent_immutable()")
    for table,column in CYCLES:
        for fk in sa.inspect(connection).get_foreign_keys(table):
            if fk['constrained_columns']==[column]:
                op.execute(f'ALTER TABLE "{table}" ALTER CONSTRAINT "{fk["name"]}" DEFERRABLE INITIALLY IMMEDIATE')


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM account_erasure)")).scalar():
        raise RuntimeError("Cannot remove account deletion replay protection")
    for table, column in CYCLES:
        for fk in sa.inspect(op.get_bind()).get_foreign_keys(table):
            if fk['constrained_columns'] == [column]:
                op.execute(f'ALTER TABLE "{table}" ALTER CONSTRAINT "{fk["name"]}" NOT DEFERRABLE')
    for table in KEYS:
        op.execute(f'DROP TRIGGER aa_account_erasure ON "{table}"')
    functions=op.get_bind().execute(sa.text("SELECT pg_get_functiondef(oid) FROM pg_proc WHERE prokind='f' AND pronamespace=current_schema()::regnamespace AND prorettype='trigger'::regtype")).scalars().all()
    for definition in functions:
        if INJECTION in definition:op.execute(definition.replace(INJECTION,''))
    op.execute("DROP TRIGGER account_permit_scope ON account_erasure_permit")
    op.execute("DROP TRIGGER account_intent_guard ON account_erasure")
    for name,args in [('account_write_guard',''),('account_permit_guard',''),('account_intent_immutable',''),('account_delete_allowed','text,jsonb'),('account_row_key','text,jsonb'),('account_row_owner','text,jsonb')]:
        op.execute(f'DROP FUNCTION {name}({args})')
    for table in ('account_erasure_permit','account_journal_state','account_erasure'):op.drop_table(table)
