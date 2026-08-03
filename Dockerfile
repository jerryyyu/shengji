# Stage 1: build the frontend
FROM node:22-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock* ./
COPY server/shengji ./shengji
# Trained value head for the mc-vleaf hybrid (numpy weights, ~2MB — the
# server does NOT install torch; see server/shengji/rl/npnet.py)
COPY server/snapshots_v7w/ep02.npz ./snapshots_v7w/ep02.npz
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev
COPY --from=web /app/web/dist /app/web/dist

EXPOSE 8000
# Single process, single instance: game state lives in memory.
CMD ["uv", "run", "--no-dev", "shengji-server"]
