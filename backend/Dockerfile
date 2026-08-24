FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv

RUN pip install --no-cache-dir uv

# The package itself is installed editable so the bind-mounted source in
# docker-compose is what actually runs.
COPY pyproject.toml ./
COPY app ./app
RUN uv pip install --system --no-cache -e '.[dev]'

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
