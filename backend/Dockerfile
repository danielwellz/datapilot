# No `# syntax=` line: the engine's built-in Dockerfile frontend supports
# everything used here (including RUN --mount), and the docker/dockerfile
# image would be one more anonymous pull from Docker Hub.

# --- Dependencies -----------------------------------------------------------
# uv installs exactly the locked runtime dependencies into a virtualenv that
# the final image copies; uv itself and the build caches stay behind.
FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

FROM public.ecr.aws/docker/library/python:3.12.15-slim-trixie AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# --- Runtime ----------------------------------------------------------------
FROM public.ecr.aws/docker/library/python:3.12.15-slim-trixie AS runtime

RUN groupadd --system --gid 10001 datapilot \
    && useradd --system --uid 10001 --gid datapilot --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin datapilot

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=app

WORKDIR /srv/backend
COPY --from=dependencies /opt/venv /opt/venv
# Owned by root and read-only for the app user: a compromised process
# cannot change the code it runs.
COPY app ./app
COPY migrations ./migrations
COPY gunicorn.conf.py ./
RUN python -m compileall -q app migrations

USER datapilot:datapilot
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"]

CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:create_app()"]
