from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url="/api/v1/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_HOST],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api/v1")


@app.exception_handler(RequestValidationError)
async def safe_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Pydantic errors can include the rejected Key or malformed JSON body.
    from fastapi.exception_handlers import request_validation_exception_handler

    if request.url.path.rstrip("/") in {"/api/v1/password-reset/request", "/api/v1/password-reset/confirm"}:
        return JSONResponse(status_code=422, content={"detail": "邮箱、链接或密码格式不正确；新密码须为 12–128 字符"})
    if request.url.path.rstrip("/") == "/api/v1/model-config":
        return JSONResponse(
            status_code=422,
            content={"detail": "配置格式不正确，请检查地址、模型 ID 和 Key"},
        )
    return await request_validation_exception_handler(request, exc)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


frontend = Path(__file__).parent / "frontend"
if frontend.exists():
    app.frontend("/", directory=frontend)
