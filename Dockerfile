# Multi-stage Dockerfile for IRIS production deployment

# Stage 1: Build frontend
FROM node:22-slim AS frontend
WORKDIR /app/iris-app
COPY iris-app/package*.json .
RUN npm ci
COPY iris-app/ .
RUN npm run build

# Stage 2: Install Python dependencies
FROM python:3.12-slim AS backend
RUN pip install uv
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN uv sync --extra daemon --no-dev

# Stage 3: Production image
FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*
RUN pip install uv

WORKDIR /app

# Copy Python environment
COPY --from=backend /app/.venv /app/.venv
COPY --from=backend /app/pyproject.toml .
COPY src/ src/
COPY configs/ configs/
COPY projects/TEMPLATE/ projects/TEMPLATE/

# Copy built frontend
COPY --from=frontend /app/dist ./dist

# Copy server files
COPY iris-app/server ./iris-app/server
COPY iris-app/package*.json ./iris-app/
RUN cd iris-app && npm ci --production

# Environment
ENV IRIS_ROOT=/app
ENV NODE_ENV=production
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 3001

# Start Express server (which auto-starts the Python daemon)
CMD ["node", "iris-app/server/index.js"]
