from fastapi import APIRouter

from app.api.routes.accounts import router
from app.capabilities.routes import router as capabilities_router
from app.model_config.routes import router as model_config_router
from app.project.routes import router as project_router
from app.training.boss_routes import router as boss_router
from app.training.concepts import router as concepts_router
from app.training.drafts import router as drafts_router
from app.training.evaluations import router as evaluations_router
from app.training.independent_routes import router as independent_router
from app.training.jds import router as jds_router
from app.training.practices import router as practices_router
from app.training.reviews import router as reviews_router
from app.training.routes import router as training_router
from app.training.submissions import router as submissions_router
from app.training.topics import router as topics_router

api_router = APIRouter()
api_router.include_router(router)
api_router.include_router(capabilities_router)
api_router.include_router(model_config_router)


api_router.include_router(training_router)

api_router.include_router(submissions_router)

api_router.include_router(project_router)


api_router.include_router(evaluations_router)


api_router.include_router(concepts_router)

api_router.include_router(drafts_router)


api_router.include_router(practices_router)
api_router.include_router(independent_router)
api_router.include_router(boss_router)


api_router.include_router(topics_router)


api_router.include_router(reviews_router)


api_router.include_router(jds_router)
