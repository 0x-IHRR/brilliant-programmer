"""Read existing attempt identities; missing provider values remain unknown."""

import uuid

from pydantic import BaseModel
from sqlalchemy import BigInteger, Column, UniqueConstraint, text
from sqlmodel import Field, Session, SQLModel

from app.core.db import engine


class ProbeAttempt(SQLModel, table=True):
    __tablename__ = "probe_attempt"
    __table_args__ = (UniqueConstraint("operation_id", "number"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    operation_id: uuid.UUID
    number: int
    kind: str
    destination: str
    model_id: str
    code: str = "not_dispatched"
    prompt_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    completion_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))
    total_tokens: int | None = Field(default=None, sa_column=Column(BigInteger))


class UsageCall(BaseModel):
    id: uuid.UUID
    kind: str
    task_id: uuid.UUID
    config_version: uuid.UUID | None
    destination: str
    model_id: str
    number: int
    code: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


class TokenTotal(BaseModel):
    known: int
    unknown_calls: int


class UsageReport(BaseModel):
    calls: list[UsageCall]
    totals: dict[str, TokenTotal]


def report(session: Session, user_id: uuid.UUID) -> UsageReport:
    # UNION ALL is safe: each domain joins its immutable attempt PK once. Reading
    # again never appends or charges; late usage updates the same persisted identity.
    queries = []
    for kind, attempt, task, task_pk, owner_join in (
        ("generation", "training_attempt", "training_run", "id", "t.user_id"),
        ("project", "project_attempt", "project_run", "id", "t.user_id"),
        ("submission", "submission_attempt", "training_submission", "id", "r.user_id"),
        (
            "evaluation",
            "evaluation_attempt",
            "training_evaluation",
            "run_id",
            "r.user_id",
        ),
        ("help", "concept_attempt", "concept_help", "id", "r.user_id"),
    ):
        fk = (
            "submission_id"
            if kind == "submission"
            else "help_id"
            if kind == "help"
            else "run_id"
        )
        extra = (
            " JOIN training_run r ON r.id=t.run_id" if owner_join == "r.user_id" else ""
        )
        label = (
            "CASE WHEN t.practice_help_id IS NULL THEN 'submission' ELSE 'practice' END"
            if kind == "submission"
            else f"'{kind}'"
        )
        queries.append(
            f"SELECT a.id,{label} AS kind,t.{task_pk} AS task_id,t.config_version,t.destination,t.model_id,a.number,a.code,a.prompt_tokens,a.completion_tokens,a.total_tokens FROM {attempt} a JOIN {task} t ON a.{fk}=t.{task_pk}{extra} WHERE {owner_join}=:user_id"
        )
    queries.append(
        "SELECT id,kind,operation_id AS task_id,NULL::uuid AS config_version,destination,model_id,number,code,prompt_tokens,completion_tokens,total_tokens FROM probe_attempt WHERE user_id=:user_id AND code<>'not_dispatched'"
    )
    calls = [
        UsageCall.model_validate(dict(row))
        for row in session.execute(
            text(" UNION ALL ".join(queries)), {"user_id": user_id}
        ).mappings()
    ]
    return UsageReport(
        calls=calls,
        totals={
            field: TokenTotal(
                known=sum(getattr(call, field) or 0 for call in calls),
                unknown_calls=sum(getattr(call, field) is None for call in calls),
            )
            for field in ("prompt_tokens", "completion_tokens", "total_tokens")
        },
    )


def start_probe(
    user_id: uuid.UUID,
    operation_id: uuid.UUID,
    number: int,
    kind: str,
    destination: str,
    model_id: str,
) -> uuid.UUID:
    with Session(engine) as session:
        item = ProbeAttempt(
            user_id=user_id,
            operation_id=operation_id,
            number=number,
            kind="probe_" + kind,
            destination=destination,
            model_id=model_id,
        )
        session.add(item)
        session.commit()
        return item.id


def record_probe(identity: uuid.UUID, code: str, counts: dict[str, int | None]) -> None:
    with Session(engine) as session:
        item = session.get(ProbeAttempt, identity)
        assert item
        item.code = code
        for field, value in counts.items():
            setattr(item, field, value)
        session.add(item)
        session.commit()
