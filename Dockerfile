# syntax=docker/dockerfile:1.7

FROM node:20.19.4-alpine3.22 AS frontend-build

WORKDIR /frontend
COPY qlib-dashboard/package.json qlib-dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY qlib-dashboard/ ./
RUN npm run lint \
    && npx --no-install tsc --noEmit \
    && npm test \
    && npm run build


FROM python:3.10.18-slim-bookworm AS python-deps

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.10 /uv /usr/local/bin/uv
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project


FROM python:3.10.18-slim-bookworm AS runtime

ENV ALPHA_ENGINE_ENV=production \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    HOME=/home/alpha \
    MPLCONFIGDIR=/tmp/matplotlib \
    PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRADING_ARTIFACTS_DIR=/app/artifacts \
    TRADING_CONFIG_DIR=/app/configs \
    TRADING_DATA_DIR=/app/data \
    TRADING_REPORTS_DIR=/app/reports \
    TRADING_STATIC_SITE_DIR=/app/qlib-dashboard/dist \
    UV_NO_CACHE=1 \
    UV_NO_SYNC=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    XDG_CACHE_HOME=/tmp/cache

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 alpha \
    && useradd --uid 10001 --gid alpha --create-home --home-dir /home/alpha alpha

WORKDIR /app

COPY --from=python-deps /opt/venv /opt/venv
COPY --from=python-deps /usr/local/bin/uv /usr/local/bin/uv
COPY --chown=alpha:alpha pyproject.toml uv.lock ./
COPY --chown=alpha:alpha api_server.py ./
COPY --chown=alpha:alpha src/ ./src/
COPY --chown=alpha:alpha configs/ ./configs/
# Only include scripts needed at runtime.  Dev/test/research scripts are excluded.
COPY --chown=alpha:alpha \
    scripts/__init__.py \
    scripts/arena_settle.py \
    scripts/build_dashboard_db.py \
    scripts/collect_data.py \
    scripts/daily_run.py \
    scripts/doctor.py \
    scripts/e2e_smoke.py \
    scripts/export_reports_zip.py \
    scripts/export_static_site_data.py \
    scripts/strategy_to_workflow.py \
    scripts/update_data.py \
    scripts/container-healthcheck.py \
    ./scripts/
COPY --chown=alpha:alpha scripts/container-entrypoint.sh ./scripts/container-entrypoint.sh
COPY --chown=alpha:alpha agents/governance/scripts/doctor.py ./agents/governance/scripts/doctor.py
COPY --chown=alpha:alpha agents/governance/scripts/sync_governance.py ./agents/governance/scripts/sync_governance.py
COPY --chown=alpha:alpha agents/risk/scripts/force_quality_check.py ./agents/risk/scripts/force_quality_check.py
COPY --chown=alpha:alpha docs/methodology.md ./docs/methodology.md
COPY --from=frontend-build --chown=alpha:alpha /frontend/dist ./qlib-dashboard/dist/

RUN mkdir -p /app/artifacts /app/data /app/mlruns /app/reports \
    && cp -a /app/configs /app/configs.bak \
    && chmod 0555 /app/scripts/container-entrypoint.sh \
    && chown -R alpha:alpha /app /home/alpha

USER 10001:10001

EXPOSE 8000
VOLUME ["/app/data", "/app/artifacts", "/app/mlruns", "/app/reports"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "/app/scripts/container-healthcheck.py"]

ENTRYPOINT ["/app/scripts/container-entrypoint.sh"]
CMD ["python", "api_server.py"]
