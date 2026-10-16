FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 10001 croppulse
WORKDIR /app
COPY backend/pyproject.toml backend/
COPY backend/croppulse backend/croppulse
RUN pip install ./backend
COPY backend/alembic.ini backend/
COPY backend/migrations backend/migrations
COPY config config
COPY scripts scripts
RUN mkdir -p data && chown -R croppulse /app/data
USER croppulse
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
CMD ["sh", "-c", "alembic upgrade head && uvicorn croppulse.api.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
