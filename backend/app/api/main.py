from fastapi import APIRouter

from app.api.routes.accounts import router
from app.capabilities.routes import router as capabilities_router
from app.model_config.routes import router as model_config_router
from app.project.routes import router as project_router
from app.training.routes import router as training_router
from app.training.submissions import router as submissions_router

api_router = APIRouter()
api_router.include_router(router)
api_router.include_router(capabilities_router)
api_router.include_router(model_config_router)


api_router.include_router(training_router)

api_router.include_router(submissions_router)

api_router.include_router(project_router)
