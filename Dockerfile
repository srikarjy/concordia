FROM node:22-bookworm-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Hash-pinned, so a rebuild of this image installs the same bytes. Regenerate with
# make space-lock after editing requirements-space.txt.
COPY requirements-space.lock.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements-space.lock.txt
COPY src ./src
RUN python -c "from concordia.api.workspace import create_workspace_app; create_workspace_app('/tmp/concordia-space-smoke')"
COPY --from=frontend-build /build/frontend/dist ./frontend/dist
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin concordia \
    && mkdir -p /app/.concordia \
    && chown -R concordia:concordia /app/.concordia
USER concordia
EXPOSE 7860
CMD ["uvicorn", "concordia.api.workspace:create_workspace_app", "--factory", "--host", "0.0.0.0", "--port", "7860"]
