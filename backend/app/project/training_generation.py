"""Small adapters for the shared ordinary and independent candidate pipeline."""

import json
import uuid
from typing import Any, Literal

from sqlmodel import Session

from app.project.training_models import ProjectMaterials
from app.project.training_rules import Selection, validate_project_candidate
from app.training.schema import Candidate
from app.training.topic_rules import Goal


class ConfirmedProjectGoal(Goal):
    material_origins: str = "[]"
    module_path: str
    repository_commit: str
    simulation_label: Literal["教学模拟"] = "教学模拟"


def goal(selection: dict[str, Any]) -> ConfirmedProjectGoal:
    frozen = Selection.model_validate_json(json.dumps(selection["project"]))
    return ConfirmedProjectGoal(
        target=frozen.goal.target,
        text=frozen.goal.text,
        focus=frozen.goal.focus,
        module_path=frozen.module_path,
        repository_commit=f"{frozen.repository.owner}/{frozen.repository.name}@{frozen.repository.commit}",
    )


def accept_materials(
    session: Session, identity: uuid.UUID, selection: dict[str, Any], raw: str, key: str
) -> Candidate:
    value = validate_project_candidate(
        raw, Selection.model_validate_json(json.dumps(selection["project"])), key
    )
    origins = [m.model_dump(mode="json") for m in value.materials]
    stored = session.get(ProjectMaterials, identity)
    if stored and stored.origins != origins:
        raise ValueError("project material checkpoint changed")
    if not stored:
        session.add(ProjectMaterials(run_id=identity, origins=origins))
    return value.case


def inspection_goal(
    session: Session, identity: uuid.UUID, selection: dict[str, Any]
) -> ConfirmedProjectGoal:
    value = goal(selection)
    row = session.get(ProjectMaterials, identity)
    if not row:
        raise ValueError("missing project material origins")
    return value.model_copy(
        update={"material_origins": json.dumps(row.origins, ensure_ascii=False)}
    )
