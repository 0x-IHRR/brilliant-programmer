from fastapi import APIRouter

from app.api.routes.accounts import router
from app.model_config.routes import router as model_config_router

api_router = APIRouter()
api_router.include_router(router)

api_router.include_router(model_config_router)
