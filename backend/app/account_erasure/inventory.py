"""Explicit owner paths, not a search-and-delete of arbitrary JSON or all tables.

Only the three Boss backreferences need deferred constraints. Other foreign keys
keep immediate checks. Every deletion is authorized by its pre-captured exact PK.
"""

# Children before parents, with only Boss revalidation cycles deferred.
TABLES = (
    "boss_revalidation", "project_route_update", "boss_promotion", "practice_award",
    "capability_original_order", "submission_attempt", "review_award", "review_attempt",
    "project_training_version", "jd_route", "jd_analysis", "practice_draft",
    "concept_attempt", "help_confirmation", "draft_collection", "training_submission",
    "help_delivery", "evaluation_attempt", "score_review", "boss_disposition",
    "project_training_input", "project_route_family", "topic_attempt", "jd_document",
    "quality_disposition", "training_draft", "concept_help", "independent_observation",
    "training_attempt", "training_evaluation", "independent_work", "boss_attempt",
    "project_training_materials", "topic_case", "topic_version", "jd_topic",
    "project_topic", "topic_job", "project_attempt", "erased_object",
    "erased_attachment", "erased_row", "quality_report", "training_run",
    "emailverification", "topic", "project_run", "probe_attempt", "archived_object",
    "loginsession", "opened_unit", "random_preference", "model_config", "passwordreset",
    "deletion_request", "user",
)
