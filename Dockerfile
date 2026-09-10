FROM node:22-bookworm-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements-space.txt ./
RUN pip install --no-cache-dir -r requirements-space.txt
COPY src ./src
COPY --from=frontend-build /build/frontend/dist ./frontend/dist
EXPOSE 7860
CMD ["uvicorn", "concordia.api.workspace:create_workspace_app", "--factory", "--host", "0.0.0.0", "--port", "7860"]
