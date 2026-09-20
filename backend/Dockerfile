FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
COPY app ./app

# Production image: only runtime dependencies, runs as a non-root user, code
# baked in rather than bind-mounted. Built with `--target prod`
# (docker-compose.prod.yml does this); plain `docker compose build` still
# gets the dev image below, unaffected.
FROM base AS prod

RUN uv pip install --system --no-cache -e '.'
COPY . .
RUN useradd --create-home --uid 10001 app && chown -R app:app /srv
USER app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Dev image: kept as the default (last) stage so the existing docker-compose.yml,
# which builds without a --target, is unaffected. Installs test/lint tooling
# and expects the bind-mounted source in docker-compose.yml to be what
# actually runs — the package is installed editable for that reason.
FROM base AS dev

RUN uv pip install --system --no-cache -e '.[dev]'
COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
