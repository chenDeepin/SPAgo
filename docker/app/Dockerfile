# SPAgo app image.
# Stage 1 builds the web bundle with Node; stage 2 is the Python runtime that
# serves the API and the built frontend from one process.
FROM node:22-bookworm-slim AS webbuild
WORKDIR /build
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SPAGO_FIXTURE_DIR=/app/data/fixtures \
    SPAGO_DEPICTION_CACHE_DIR=/app/data/cache/depictions

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
      libxrender1 libxext6 libsm6 libice6 libexpat1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY LICENSE NOTICE THIRD_PARTY_NOTICES.md ./licenses/
COPY services/core/pyproject.toml services/core/README.md ./services/core/
COPY services/core/spago_core ./services/core/spago_core
RUN pip install --no-cache-dir ./services/core

COPY scripts/extract_surechembl.py ./scripts/extract_surechembl.py
COPY migrations ./migrations
COPY data/fixtures ./data/fixtures
COPY --from=webbuild /build/dist ./web

EXPOSE 8000

CMD ["sh", "-c", "python -m spago_core.seed && uvicorn spago_core.main:app --host 0.0.0.0 --port 8000"]
