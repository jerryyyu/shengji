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
# Learned override (rl-override-v11pair). Numpy weights, ~2MB, parity with
# torch asserted from committed fixtures in tests/test_npnet_prod_parity.py.
# Only used when SHENGJI_BOT names it; the default is still mc.
COPY server/snapshots_v11pair/ep07.npz ./snapshots_v11pair/ep07.npz
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev
COPY --from=web /app/web/dist /app/web/dist

EXPOSE 8000
# Single process, single instance: game state lives in memory.
CMD ["uv", "run", "--no-dev", "shengji-server"]
