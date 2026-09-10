"""Scoped erasure receipts, empty-only immutable exceptions and replay guards."""

import json
import re

from alembic import op
import sqlalchemy as sa

revision = "0028_permanent_deletion"
down_revision = "0027_project_updates"
branch_labels = None
depends_on = None

# Frozen migration inventory; do not import mutable application erasure policy.
KEYS = {
    "training_run": "id", "training_submission": "id", "training_evaluation": "run_id",
    "score_review": "run_id", "concept_help": "id", "help_delivery": "id",
    "training_draft": "run_id", "practice_draft": "help_id", "draft_collection": "scope_key",
    "independent_work": "run_id", "topic_case": "run_id", "topic_version": "id",
    "topic_job": "id", "jd_document": "id", "jd_analysis": "document_id",
    "jd_route": "version_id", "project_run": "id", "project_training_input": "id",
    "project_training_version": "version_id", "project_training_materials": "run_id",
    "quality_report": "id", "quality_evidence": "sha256",
}
INJECTION = "\nIF TG_OP = 'DELETE' AND TG_TABLE_NAME = 'quality_evidence' AND erasure_blob_allowed(to_jsonb(OLD)->>'sha256') THEN RETURN OLD; END IF;\nIF TG_OP = 'UPDATE' AND erasure_change_allowed(TG_TABLE_NAME, to_jsonb(OLD), to_jsonb(NEW)) THEN RETURN NEW; END IF;\n"


STATUS_VALUES = {
    "training_submission": "'checking','needs_supplement','failed','completed','stopping','stopped'",
    "project_run": "'queued','running','completed','failed','stopping','stopped'",
}


def status_constraints(deleted):
    for table, values in STATUS_VALUES.items():
        op.drop_constraint(table + "_status_check", table, type_="check")
        allowed = values + (",'deleted'" if deleted else "")
        op.create_check_constraint(table + "_status_check", table, "status IN (" + allowed + ")")


def upgrade():
    status_constraints(True)
    op.create_table("deletion_request",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("scope_digest", sa.String(), nullable=False),
        sa.Column("authentication_digest", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_deletion_request_user_id", "deletion_request", ["user_id"])
    op.create_table("erased_object",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), primary_key=True),
        sa.Column("kind", sa.String(), primary_key=True),
        sa.Column("object_id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("deletion_request.id"), nullable=False),
        sa.Column("seen", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("erased_row",
        sa.Column("table_name", sa.String(), primary_key=True),
        sa.Column("row_key", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("deletion_request.id"), primary_key=True),
        sa.Column("cleared", sa.JSON(), nullable=False))
    op.create_index("ix_erased_row_user_id", "erased_row", ["user_id"])
    op.create_table("archived_object",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id"), primary_key=True),
        sa.Column("kind", sa.String(), primary_key=True),
        sa.Column("object_id", sa.Uuid(), primary_key=True))
    op.execute("""CREATE FUNCTION erasure_row_owner(t text, rowdata jsonb) RETURNS uuid LANGUAGE plpgsql AS $$
    DECLARE owner_id uuid; topic_identity uuid; run_identity uuid;
    BEGIN
      IF t IN ('training_run','project_run','topic_job','quality_report','topic') THEN RETURN (rowdata->>'user_id')::uuid; END IF;
      IF rowdata ? 'run_id' THEN
        SELECT user_id INTO owner_id FROM training_run WHERE id=(rowdata->>'run_id')::uuid;
        RETURN owner_id;
      END IF;
      IF rowdata ? 'topic_id' THEN topic_identity := (rowdata->>'topic_id')::uuid;
      ELSIF t='jd_analysis' THEN SELECT topic_id INTO topic_identity FROM jd_document WHERE id=(rowdata->>'document_id')::uuid;
      ELSIF rowdata ? 'version_id' THEN SELECT topic_id INTO topic_identity FROM topic_version WHERE id=(rowdata->>'version_id')::uuid;
      END IF;
      SELECT user_id INTO owner_id FROM topic WHERE id=topic_identity;
      RETURN owner_id;
    END $$""")
    op.execute("""CREATE FUNCTION validate_erasure_marker() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE policy jsonb; rowdata jsonb; key_column text;
    BEGIN
      policy := '{"training_run": {"selection": {}, "sources": [], "candidate": null, "message": "记录已永久删除", "stop_requested": true, "status": "deleted", "code": "deleted"}, "training_submission": {"answers": [], "relevance": [], "message": "记录已永久删除", "stop_requested": true, "status": "deleted", "code": "deleted"}, "training_evaluation": {"inputs": {}, "case_snapshot": {}, "sources": [], "result": null, "message": "记录已永久删除", "stop_requested": true, "status": "deleted", "code": "deleted"}, "score_review": {"snapshot": {}, "opinion": null, "message": "记录已永久删除", "stop_requested": true, "status": "deleted", "code": "deleted"}, "concept_help": {"request": {}, "content": null, "inspection": null, "message": "记录已永久删除", "stop_requested": true, "status": "deleted", "code": "deleted"}, "help_delivery": {"delivered_text": ""}, "training_draft": {"progress": {}}, "practice_draft": {"progress": {}}, "draft_collection": {"data": {}}, "independent_work": {"candidate": null, "history": [], "novelty": null, "history_snapshot": null, "comparison_plan": null, "comparison_results": []}, "topic_case": {"candidate": {}}, "topic_version": {"snapshot": {}}, "topic_job": {"input_text": "", "candidate": null, "message": "来源已永久删除", "stop_requested": true, "status": "deleted", "code": "deleted"}, "jd_document": {"text": ""}, "jd_analysis": {"snapshot": {}}, "jd_route": {"snapshot": {}}, "project_run": {"url": "", "snapshot": null, "project_map": null, "message": "来源已永久删除", "stop_requested": true, "status": "deleted", "code": "deleted"}, "project_training_input": {"snapshot": {}, "project_map": {}}, "project_training_version": {"snapshot": {}}, "project_training_materials": {"origins": []}, "quality_report": {"report": {}}, "quality_evidence": {"content": "\\\\x"}}'::jsonb -> NEW.table_name;
      IF policy IS NULL OR NEW.cleared::jsonb='{}'::jsonb OR NOT policy @> NEW.cleared::jsonb THEN RAISE EXCEPTION 'invalid erasure field scope'; END IF;
      key_column := '{"training_run": "id", "training_submission": "id", "training_evaluation": "run_id", "score_review": "run_id", "concept_help": "id", "help_delivery": "id", "training_draft": "run_id", "practice_draft": "help_id", "draft_collection": "scope_key", "independent_work": "run_id", "topic_case": "run_id", "topic_version": "id", "topic_job": "id", "jd_document": "id", "jd_analysis": "document_id", "jd_route": "version_id", "project_run": "id", "project_training_input": "id", "project_training_version": "version_id", "project_training_materials": "run_id", "quality_report": "id", "quality_evidence": "sha256"}'::jsonb ->> NEW.table_name;
      EXECUTE format('SELECT to_jsonb(r) FROM %I r WHERE %I::text=$1', NEW.table_name,key_column) INTO rowdata USING NEW.row_key;
      IF erasure_row_owner(NEW.table_name,rowdata) IS DISTINCT FROM NEW.user_id THEN RAISE EXCEPTION 'erasure row belongs to another owner'; END IF;
      IF NOT EXISTS (SELECT 1 FROM deletion_request WHERE id=NEW.request_id AND user_id=NEW.user_id AND completed_at IS NULL) THEN RAISE EXCEPTION 'erasure owner differs'; END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER erasure_marker_scope BEFORE INSERT ON erased_row FOR EACH ROW EXECUTE FUNCTION validate_erasure_marker()")
    op.execute("""CREATE FUNCTION validate_erasure_root() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE t text; owner_id uuid;
    BEGIN
      t := CASE NEW.kind WHEN 'training' THEN 'training_run' WHEN 'evidence' THEN 'training_run' WHEN 'project' THEN 'project_run' WHEN 'topic' THEN 'topic' WHEN 'quality' THEN 'quality_report' END;
      IF t IS NULL THEN RAISE EXCEPTION 'invalid erased root kind'; END IF;
      EXECUTE format('SELECT user_id FROM %I WHERE id=$1',t) INTO owner_id USING NEW.object_id;
      IF owner_id IS DISTINCT FROM NEW.user_id OR NOT EXISTS (SELECT 1 FROM deletion_request WHERE id=NEW.request_id AND user_id=NEW.user_id AND completed_at IS NULL) THEN RAISE EXCEPTION 'invalid erased root owner or receipt'; END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER erasure_root_scope BEFORE INSERT ON erased_object FOR EACH ROW EXECUTE FUNCTION validate_erasure_root()")
    op.execute("""CREATE FUNCTION deletion_receipt_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'deletion receipt is immutable'; END IF;
      IF (to_jsonb(NEW)-'completed_at') IS DISTINCT FROM (to_jsonb(OLD)-'completed_at') OR (OLD.completed_at IS NOT NULL AND NEW.completed_at IS DISTINCT FROM OLD.completed_at) THEN RAISE EXCEPTION 'deletion receipt is immutable'; END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER deletion_receipt_guard BEFORE UPDATE OR DELETE ON deletion_request FOR EACH ROW EXECUTE FUNCTION deletion_receipt_immutable()")
    op.create_table("erased_attachment", sa.Column("request_id", sa.Uuid(), sa.ForeignKey("deletion_request.id"), primary_key=True), sa.Column("sha256", sa.String(), primary_key=True))
    op.execute("""CREATE FUNCTION erasure_blob_allowed(sha text) RETURNS boolean LANGUAGE sql AS $$
      SELECT EXISTS (SELECT 1 FROM erased_attachment a JOIN deletion_request d ON d.id=a.request_id WHERE a.sha256=sha AND d.completed_at IS NULL)
      AND NOT EXISTS (SELECT 1 FROM quality_report WHERE jsonb_path_exists(report::jsonb, '$.** ? (@ == $sha)', jsonb_build_object('sha',sha)))
    $$""")
    key_map = json.dumps(KEYS).replace("'", "''")
    op.execute(f"""CREATE FUNCTION erasure_key(t text, r jsonb) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT r ->> ('{key_map}'::jsonb ->> t) $$""")
    op.execute("""CREATE FUNCTION erasure_change_allowed(t text, oldrow jsonb, newrow jsonb) RETURNS boolean LANGUAGE plpgsql AS $$
    DECLARE replacement jsonb; field_names text[];
    BEGIN
      SELECT jsonb_object_agg(e.key,e.value) INTO replacement FROM erased_row r CROSS JOIN LATERAL jsonb_each(r.cleared::jsonb) e WHERE r.table_name=t AND r.row_key=erasure_key(t,oldrow);
      IF replacement IS NULL THEN RETURN false; END IF;
      SELECT array_agg(key) INTO field_names FROM jsonb_each(replacement);
      RETURN (newrow - field_names) = (oldrow - field_names) AND NOT EXISTS (SELECT 1 FROM jsonb_each(replacement) e WHERE newrow->e.key IS DISTINCT FROM e.value);
    END $$""")
    # Preserve each actual immutable trigger body; only the marker-bound,
    # empty-only update can bypass its old rejection, never arbitrary updates.
    connection = op.get_bind()
    functions = connection.execute(sa.text("""SELECT DISTINCT p.oid, pg_get_functiondef(p.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT t.tgisinternal AND n.nspname=current_schema() AND c.relname=ANY(:tables)"""), {"tables": list(KEYS)}).all()
    for _, definition in functions:
        op.execute(re.sub(r"\bBEGIN\b", lambda m: m.group(0) + INJECTION, definition, count=1, flags=re.I))
    op.execute("""CREATE FUNCTION prevent_erased_write() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE replacement jsonb; root_id uuid; root_kind text; rowdata jsonb;
    BEGIN
      rowdata := to_jsonb(NEW);
      SELECT jsonb_object_agg(e.key,e.value) INTO replacement FROM erased_row r CROSS JOIN LATERAL jsonb_each(r.cleared::jsonb) e WHERE r.table_name=TG_TABLE_NAME AND r.row_key=erasure_key(TG_TABLE_NAME,rowdata);
      IF replacement IS NOT NULL THEN
        IF TG_OP='INSERT' OR EXISTS (SELECT 1 FROM jsonb_each(replacement) e WHERE rowdata->e.key IS DISTINCT FROM e.value) THEN RAISE EXCEPTION 'permanently erased content cannot be restored'; END IF;
        RETURN NEW;
      END IF;
      IF TG_TABLE_NAME IN ('training_run','project_run','topic') THEN
        root_kind := CASE TG_TABLE_NAME WHEN 'training_run' THEN 'training' WHEN 'project_run' THEN 'project' ELSE 'topic' END;
        root_id := (rowdata->>'id')::uuid;
      ELSIF TG_TABLE_NAME='project_attempt' THEN root_kind := 'project'; root_id := (rowdata->>'run_id')::uuid;
      ELSIF TG_TABLE_NAME='topic_attempt' THEN root_kind := 'topic'; SELECT topic_id INTO root_id FROM topic_job WHERE id=(rowdata->>'run_id')::uuid;
      ELSIF TG_TABLE_NAME='submission_attempt' THEN root_kind := 'training'; SELECT run_id INTO root_id FROM training_submission WHERE id=(rowdata->>'submission_id')::uuid;
      ELSIF TG_TABLE_NAME='capability_original_order' THEN root_kind := 'training'; SELECT run_id INTO root_id FROM training_submission WHERE id=(rowdata->>'original_id')::uuid;
      ELSIF TG_TABLE_NAME='concept_attempt' THEN root_kind := 'training'; SELECT run_id INTO root_id FROM concept_help WHERE id=(rowdata->>'help_id')::uuid;
      ELSIF TG_TABLE_NAME='jd_analysis' THEN root_kind := 'topic'; SELECT topic_id INTO root_id FROM jd_document WHERE id=(rowdata->>'document_id')::uuid;
      ELSIF TG_TABLE_NAME IN ('jd_route','project_training_version') THEN root_kind := 'topic'; SELECT topic_id INTO root_id FROM topic_version WHERE id=(rowdata->>'version_id')::uuid;
      ELSIF rowdata ? 'run_id' THEN root_kind := 'training'; root_id := (rowdata->>'run_id')::uuid;
      ELSIF rowdata ? 'topic_id' THEN root_kind := 'topic'; root_id := (rowdata->>'topic_id')::uuid;
      END IF;
      IF TG_OP='INSERT' AND root_id IS NOT NULL AND EXISTS (SELECT 1 FROM erased_object WHERE kind=root_kind AND object_id=root_id) THEN RAISE EXCEPTION 'permanently erased object cannot accept new writes'; END IF;
      RETURN NEW;
    END $$""")
    guarded = set(KEYS) | {"topic", "training_attempt", "submission_attempt", "evaluation_attempt", "concept_attempt", "review_attempt", "project_attempt", "topic_attempt", "practice_award", "review_award", "capability_original_order", "independent_observation", "help_confirmation", "boss_attempt", "boss_promotion", "boss_disposition", "quality_disposition"}
    for table in sorted(guarded):
        op.execute(f"CREATE TRIGGER aa_erasure_guard BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION prevent_erased_write()")
    for table in ("erased_object", "erased_row", "erased_attachment"):
        op.execute(f"CREATE TRIGGER deletion_marker_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION boss_fact_immutable()")


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT EXISTS (SELECT 1 FROM erased_object)")).scalar():
        raise RuntimeError("Cannot remove permanent deletion replay protection")
    status_constraints(False)
    guarded = set(KEYS) | {"topic", "training_attempt", "submission_attempt", "evaluation_attempt", "concept_attempt", "review_attempt", "project_attempt", "topic_attempt", "practice_award", "review_award", "capability_original_order", "independent_observation", "help_confirmation", "boss_attempt", "boss_promotion", "boss_disposition", "quality_disposition"}
    for table in sorted(guarded):
        op.execute(f"DROP TRIGGER aa_erasure_guard ON {table}")
    functions = connection.execute(sa.text("SELECT pg_get_functiondef(oid) FROM pg_proc WHERE prokind='f' AND pronamespace=current_schema()::regnamespace AND prorettype='trigger'::regtype")).scalars().all()
    for definition in functions:
        if INJECTION in definition:
            op.execute(definition.replace(INJECTION, ""))
    op.execute("DROP TRIGGER IF EXISTS erasure_marker_scope ON erased_row")
    op.execute("DROP FUNCTION IF EXISTS validate_erasure_marker()")
    op.execute("DROP TRIGGER erasure_root_scope ON erased_object")
    op.execute("DROP FUNCTION validate_erasure_root()")
    op.execute("DROP TRIGGER deletion_receipt_guard ON deletion_request")
    op.execute("DROP FUNCTION deletion_receipt_immutable()")
    op.execute("DROP FUNCTION prevent_erased_write()")
    op.execute("DROP FUNCTION erasure_row_owner(text,jsonb)")
    op.execute("DROP FUNCTION erasure_blob_allowed(text)")
    op.execute("DROP FUNCTION erasure_change_allowed(text,jsonb,jsonb)")
    op.execute("DROP FUNCTION erasure_key(text,jsonb)")
    for table in ("archived_object", "erased_attachment", "erased_row", "erased_object", "deletion_request"):
        op.drop_table(table)
