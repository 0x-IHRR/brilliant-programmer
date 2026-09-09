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
    if request.url.path.rstrip("/") == "/api/v1/model-config" or request.url.path.startswith("/api/v1/model-config/"):
        return JSONResponse(
            status_code=422,
            content={"detail": "配置格式不正确，请检查地址、模型 ID 和 Key"},
        )
    if request.url.path.startswith("/api/v1/topics"):
        return JSONResponse(status_code=422, content={"detail": "主题或版本格式不正确；输入保留，请检查本次操作"})
    if request.url.path.startswith("/api/v1/jds"):
        return JSONResponse(status_code=422, content={"detail": "JD 或版本格式不正确；输入保留，请检查本次操作"})
    if request.url.path.startswith("/api/v1/project-training"):
        return JSONResponse(status_code=422, content={"detail": "项目路线或版本格式不正确；请保留本机输入并检查操作"})
    if request.url.path.startswith("/api/v1/projects"):
        return JSONResponse(status_code=422, content={"detail": "请检查公开 GitHub HTTPS 链接、模型目的地确认与请求格式"})
    if request.url.path.startswith("/api/v1/training/") and request.url.path.rstrip("/").endswith("/draft"):
        return JSONResponse(status_code=422, content={"detail": "草稿格式不正确，请检查题目与保存版本；未完成内容可以保存，当前输入保留"})
    if request.url.path.startswith("/api/v1/training/"):
        return JSONResponse(status_code=422, content={"detail": "请完成全部判断与非空理由，检查提交格式；原答未覆盖"})
    return await request_validation_exception_handler(request, exc)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


frontend = Path(__file__).parent / "frontend"
if frontend.exists():
    app.frontend("/", directory=frontend)
