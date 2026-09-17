FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

COPY alembic.ini ./
COPY migrations ./migrations
COPY tests ./tests

ENV PYTHONPATH=/app/src

CMD ["uvicorn", "onetake_api.main:app", "--host", "0.0.0.0", "--port", "8000"]