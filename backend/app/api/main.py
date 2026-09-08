from fastapi import APIRouter

from app.api.routes.accounts import router

api_router = APIRouter()
api_router.include_router(router)
