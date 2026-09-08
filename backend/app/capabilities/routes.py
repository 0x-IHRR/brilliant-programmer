from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.deps import get_training_user
from app.capabilities.catalog import CATALOG, Catalog
from app.models import User

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


@router.get("/catalog", response_model=Catalog)
def read_catalog(
    _user: Annotated[User, Depends(get_training_user)], response: Response
) -> Catalog:
    response.headers["Cache-Control"] = "no-store"
    return CATALOG
