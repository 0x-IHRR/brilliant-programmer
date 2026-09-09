from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.deps import SessionDep, get_training_user
from app.capabilities.catalog import CATALOG, Catalog
from app.capabilities.evidence import EvidenceMap
from app.capabilities.evidence_service import read_evidence
from app.model_config.service import lock_owner
from app.models import User

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


@router.get("/catalog", response_model=Catalog)
def read_catalog(
    _user: Annotated[User, Depends(get_training_user)], response: Response
) -> Catalog:
    response.headers["Cache-Control"] = "no-store"
    return CATALOG


@router.get("/evidence", response_model=EvidenceMap)
def read_capability_evidence(
    user: Annotated[User, Depends(get_training_user)],
    session: SessionDep,
    response: Response,
) -> EvidenceMap:
    response.headers["Cache-Control"] = "no-store"
    lock_owner(session, user.id)
    return read_evidence(session, user.id)
