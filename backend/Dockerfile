FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system aurinara-edc \
    && useradd --system --gid aurinara-edc --create-home aurinara-edc

WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY alembic ./alembic
COPY scripts ./scripts
RUN pip install --no-cache-dir --upgrade "setuptools>=78.1.1" \
    && pip install --no-cache-dir . \
    && pip uninstall --yes pip setuptools

USER aurinara-edc
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
