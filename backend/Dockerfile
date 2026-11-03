# Byggs från repots rot (docker-compose.yml och railway.json): docker build -f backend/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/alembic.ini ./
RUN pip install --no-cache-dir .

RUN useradd --create-home vskalkyl
USER vskalkyl

# Railway anger porten i $PORT; lokalt 8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
