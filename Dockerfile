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
RUN python setup.py build_ext --inplace \
    && ls -la shengji/engine/_fast*.so shengji/ai/_cwv_math*.so \
       shengji/ai/_endgame_fast*.so shengji/train/_pv_fast*.so \
       shengji/train/_reply_fast*.so

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock* ./
COPY server/shengji ./shengji
# The operator's account-suspension tool, run through `fly ssh console`.
COPY server/scripts/suspend_account.py ./scripts/suspend_account.py
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev
# The compiled extension, matched to this image's CPython. `fast.py` activates
# it only when SHENGJI_FAST=1 and falls back silently otherwise, so a missing
# or mismatched .so degrades rather than breaking.
COPY --from=fastbuild /build/shengji/engine/_fast*.so ./shengji/engine/
# Exact libc-erf loop for the compact NumPy value model; no Torch dependency.
COPY --from=fastbuild /build/shengji/ai/_cwv_math*.so ./shengji/ai/
# Compiled exact endgame solver (ai/endgame_compact.py selects it exactly when
# the compiled engine is active; otherwise its identical pure-Python twin runs).
COPY --from=fastbuild /build/shengji/ai/_endgame_fast*.so ./shengji/ai/
# Compiled kernels of the search's native latency switches (train/pv_native.py
# keeps the Python reference paths when it is absent or a switch is off).
COPY --from=fastbuild /build/shengji/train/_pv_fast*.so ./shengji/train/
# Compiled reply-children builder of the greedy finish (train/pv_tree_search.py
# builds the same children in Python when it is absent).
COPY --from=fastbuild /build/shengji/train/_reply_fast*.so ./shengji/train/
COPY --from=web /app/web/dist /app/web/dist

EXPOSE 8000
# Single process, single instance: game state lives in memory.
CMD ["uv", "run", "--no-dev", "shengji-server"]
