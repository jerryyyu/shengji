"""Run one reviewed timing packet on its isolated Fly guest."""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tarfile
import time
import tomllib
import urllib.request

ROOT = Path("/tmp/m2fly")
BIN = Path("/app/server/.venv/bin")
APP = "shengji-m2-timing"


def reference_env(config):
    keys = {"SHENGJI_BOT", "SHENGJI_MODEL_SEARCH_CONCURRENCY", "SHENGJI_FAST",
            "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "SHENGJI_DEVICE_ACCOUNTS", "GOOGLE_CLIENT_ID"}
    env = {k: v for k, v in config.items() if k.startswith(("SHENGJI_PV_", "SHENGJI_CWV_")) or k in keys}
    for key, value in env.items():
        if key.endswith("_CKPT"):
            if Path(value).parent != Path("/data/models"):
                raise ValueError(f"unexpected reference model path for {key}")
            env[key] = str(ROOT / "models" / Path(value).name)
    env.update(PATH="/usr/local/bin:/usr/bin:/bin", HOME=str(ROOT), TMPDIR=str(ROOT),
               SHENGJI_DATA_DIR=str(ROOT / "reference"), SHENGJI_LOG_DIR=str(ROOT / "reference/logs"),
               SHENGJI_TELEMETRY_DIR=str(ROOT / "reference/telemetry"), MKL_NUM_THREADS="1",
               PYTHONDONTWRITEBYTECODE="1")
    return env


def main():
    machine = os.environ.get("FLY_MACHINE_ID", "")
    digest = sys.argv[1] if len(sys.argv) == 2 else ""
    if (os.environ.get("FLY_APP_NAME") != APP or not re.fullmatch("[0-9a-f]+", machine)
            or not re.fullmatch("[a-f0-9]{64}", digest) or Path(__file__).resolve() != ROOT / "supervise.py"):
        raise ValueError("unexpected machine or packet")
    if (ROOT / "launcher.RELEASE").read_text().split() != [digest, machine]:
        raise ValueError("release must bind the reviewed archive and this machine")
    if (ROOT / "launcher.HOLD").exists() or (ROOT / "out").exists():
        raise ValueError("HOLD or existing output")
    with (ROOT / "m2fly.tgz").open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError("archive differs from RELEASE")
    with tarfile.open(ROOT / "m2fly.tgz", "r:gz") as archive:
        if archive.extractfile("SHA256SUMS").read() != (ROOT / "SHA256SUMS").read_bytes():
            raise ValueError("installed manifest differs from released archive")
    subprocess.run(["sha256sum", "--check", "--strict", "SHA256SUMS"], cwd=ROOT, check=True)
    config = tomllib.loads((ROOT / "fly.toml").read_text())["env"]
    env = reference_env(config)
    env.update(FLY_APP_NAME=APP, FLY_MACHINE_ID=machine)
    (ROOT / "started").mkdir()
    for key in ("SHENGJI_DATA_DIR", "SHENGJI_LOG_DIR", "SHENGJI_TELEMETRY_DIR"):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 2700
    with (ROOT / "server.log").open("xb") as log:
        server = subprocess.Popen([str(BIN / "uvicorn"), "shengji.api.server:app", "--host", "127.0.0.1",
                                   "--port", "8000"], cwd="/app/server", env=env, stdout=log, stderr=log)
        try:
            for _ in range(60):
                if server.poll() is not None:
                    raise RuntimeError("reference server exited during boot")
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=2) as response:
                        if json.load(response).get("bot") == config["SHENGJI_BOT"]:
                            break
                except OSError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("reference server did not become ready")
            if (ROOT / "launcher.HOLD").exists():
                raise RuntimeError("HOLD before producer")
            worker_env = dict(env, M2_TIMING_SERVER_PID=str(server.pid))
            producer = subprocess.Popen([str(BIN / "python"), "-B", str(ROOT / "timing.py"), "run"],
                                        cwd=ROOT, env=worker_env, start_new_session=True)
            try:
                while producer.poll() is None:
                    if (time.monotonic() >= deadline or (ROOT / "launcher.HOLD").exists()
                            or server.poll() is not None):
                        raise RuntimeError("wall limit, HOLD or reference process exit")
                    time.sleep(0.5)
                if producer.returncode:
                    raise RuntimeError(f"producer rc={producer.returncode}")
            finally:
                if producer.poll() is None:
                    producer.terminate()
                    try:
                        producer.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(producer.pid, signal.SIGKILL)
                producer.wait()
        finally:
            if server.poll() is None:
                server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
    out = ROOT / "out"
    seal = bytearray()
    for filename in ("decisions.jsonl", "events.jsonl", "samples.jsonl"):
        with (out / filename).open("rb") as stream:
            file_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        seal.extend(f"{file_hash}  {filename}\n".encode())
    with (out / "SHA256SUMS").open("xb") as stream:
        stream.write(seal)
    seal_digest = hashlib.sha256(seal).hexdigest()
    with (ROOT / "producer.done").open("x") as witness:
        witness.write(f"{digest} {machine} {seal_digest}\n")


if __name__ == "__main__":
    main()
