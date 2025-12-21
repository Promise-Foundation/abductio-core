FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src

RUN pip install --upgrade pip \
 && pip install .

EXPOSE 8000
CMD ["sh", "-c", "uvicorn abductio_core.adapters.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
