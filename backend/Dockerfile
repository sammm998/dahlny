# Byggs från repots rot (docker-compose.yml och railway.json): docker build -f backend/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/alembic.ini ./
RUN pip install --no-cache-dir .
# granskningsgränssnittet (statiskt) och katalogen med projektkörningar (bundle.json per projekt)
COPY frontend ./frontend
ENV VSK_UI_DIR=/app/frontend VSK_PROJECTS_DIR=/app/projekt

RUN useradd --create-home vskalkyl && mkdir -p /app/projekt && chown vskalkyl /app/projekt
USER vskalkyl

# Railway anger porten i $PORT; lokalt 8000
EXPOSE 8000
# Med DATABASE_URL körs migreringarna först (misslyckas de startar appen ändå och /health säger varför)
CMD ["sh", "-c", "if [ -n \"$DATABASE_URL\" ]; then alembic upgrade head || echo 'Migreringen misslyckades – se loggen'; fi; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
