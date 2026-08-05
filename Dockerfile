# Stage 1: build the frontend
FROM node:22-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: Python runtime
# --- stage: compile the Cython hot-path extension -------------------------
# Built in a throwaway stage so build-essential (~200MB) never reaches the
# runtime image. Without this the server falls back to pure Python, which is
# ~3x slower per decision — it was running that way in production until
# 2026-08-05, so the compiled-engine timings in AI_POLICIES.md did not
# describe prod at all.
FROM python:3.12-slim AS fastbuild
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "cython>=3.2.9" "setuptools>=68"
WORKDIR /build
COPY server/setup.py ./setup.py
COPY server/shengji ./shengji
RUN python setup.py build_ext --inplace && ls -la shengji/engine/_fast*.so

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
# The compiled extension, matched to this image's CPython. `fast.py` activates
# it only when SHENGJI_FAST=1 and falls back silently otherwise, so a missing
# or mismatched .so degrades rather than breaking.
COPY --from=fastbuild /build/shengji/engine/_fast*.so ./shengji/engine/
COPY --from=web /app/web/dist /app/web/dist

EXPOSE 8000
# Single process, single instance: game state lives in memory.
CMD ["uv", "run", "--no-dev", "shengji-server"]
