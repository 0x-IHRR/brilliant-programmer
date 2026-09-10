FROM oven/bun:1.3.4@sha256:7608db4aeb44f1fe8169cc8ec7055376b3013557b106407ccf092b00e426407d AS frontend
WORKDIR /build
COPY package.json bun.lock ./
COPY frontend/package.json frontend/package.json
RUN bun install --frozen-lockfile
COPY frontend frontend
WORKDIR /build/frontend
RUN bun run build

FROM ghcr.io/astral-sh/uv:0.10.9@sha256:10902f58a1606787602f303954cea099626a4adb02acbac4c69920fe9d278f82 AS uv
FROM python:3.14.3-slim-bookworm@sha256:f21c0d5a44c56805654c15abccc1b2fd576c8d93aca0a3f74b4aba2dc92510e2
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1 PATH=/app/.venv/bin:$PATH
COPY pyproject.toml uv.lock ./
COPY backend backend
RUN uv sync --locked --no-dev --package app
COPY --from=frontend /build/backend/app/frontend /app/backend/app/frontend
RUN useradd --uid 10001 --create-home app
USER 10001:10001
WORKDIR /app/backend
ENTRYPOINT ["python", "-m", "app.operations.runtime"]
CMD ["api"]
