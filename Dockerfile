FROM node:22-bookworm-slim AS frontend

WORKDIR /frontend
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate
COPY FE/package.json FE/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY FE/ ./
RUN pnpm run build

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*
COPY BE/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY BE/app.py ./app.py
COPY BE/geofield ./geofield
COPY --from=frontend /frontend/dist ./frontend_dist
RUN mkdir -p /app/uploads /app/cache /app/static

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
