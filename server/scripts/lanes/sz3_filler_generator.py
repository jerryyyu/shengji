"""Pin the R55 filler producer and verify its completed corpus metadata."""
from __future__ import annotations

import hashlib
import json
import re
import runpy
import subprocess
from pathlib import Path

HOME = Path.home()
FLEET = HOME / "fleet"
GENERATOR_TREE = HOME / "Projects/shengji-wt/codex-sz2r-deploy-3e00a55a"
PYTHON = HOME / "Projects/shengji/server/.venv/bin/python"
MAIN_REGISTRY = HOME / "Projects/shengji/server/runs/seed_windows.json"
MODELS = FLEET / "claude-s160-rt4attrib-v1/inputs"
SHA = "3e00a55a7a38e5a135809f601c9b47fb315fa725"
FLY_SHA = "aa3048fba371132c02704d629f0f2dbf3590458112f89058329b51b7bf4e5f29"
RUNNER_SHA = "51e4331c24f88765dee308b81e1e08f0deb00a1e415ae8d305c6a4c73cd8ca37"
FAST_SHA = "1c3eef18397b620340323df24bae42b3d66477e2827319177b7e2ba276ca0ea3"
ENGINE = "engine/_fast.cpython-314-darwin.so"
NATIVE_PINS = {
    ENGINE: FAST_SHA,
    "ai/_cwv_math.cpython-314-darwin.so": "adf84e65469ca2c15c3733a7022f68629689d9ac74cd0b5e6c8c34ae679db4b2",
    "ai/_endgame_fast.cpython-314-darwin.so": "fcb0da44e87b95c728b26ea921616962b39e6640722c0517e40de7382df9ad88",
    "train/_pv_fast.cpython-314-darwin.so": "bdbb4d9357c4dcfe7445b732f24176b36efdb39d230411370d0cd381c24f8603",
    "train/_reply_fast.cpython-314-darwin.so": "8498d6c2e3f29b138d54962ba1ea6d4472d4fb1f2b67962696bba67d2ca4ed63",
}
MODEL_PINS = {
    "ut-rt4-e2951d35.npz": "e2951d35eeabd167347c3b5608a8065dffb9bd304b51aa4759eabbba1ce05883",
    "ut-rt4-belief-35e225cf.npz": "35e225cf3afd460d231a44192e60be8595a5d7fce81c860f0bfe3153506f66e3",
    "g3a-e04-f4f4127e.npz": "f4f4127ec0c8821b4aa07f7d651a4258c696f97a874707da2c78ad26c0c9b9fd",
    "p0-ft1-1fa201b2.npz": "1fa201b288e78b3072979f55030aae44711ee214b50a14e155d0bbe11b6bb1bf",
}
POLICY = (
    "pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-rcec-whl-whd-wht-bw-tb-ele-elt-elm-la-dtr-dtrx-vd-"
    "vdef-lgf-lgfx-lgfd2000-ed7-els1600-xf7-xfcompactlevel-reac0a771-bury-hybrid-bwv-bbw-e191a6461fa8-"
    "sc8-usharee2951d35-uvaluee2951d35-ureplye2951d35-ufast"
)
SEED = 1011000000
ROUNDS = 2000
WORKERS = 8
_METADATA_LIMIT = 4 * 1024 * 1024
_SIDECAR_LIMIT = 32 * 1024
_HEX_SHA = re.compile(r"[0-9a-f]{64}")


def generator_environment() -> dict[str, str]:
    """Isolate the producer from inherited policy, backend and thread settings."""
    return {
        "HOME": str(HOME), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
    }


def _checked_output(argv: list[str], *, cwd: Path) -> str:
    result = subprocess.run(argv, cwd=cwd, env=generator_environment(), timeout=30,
                            text=True, capture_output=True)
    if result.returncode:
        raise ValueError(f"{Path(argv[0]).name} preflight failed: {result.stderr.strip()[-500:]}")
    return result.stdout


def _verify_file(path: Path, expected: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or linked pinned file: {path}")
    with path.open("rb") as file:
        if hashlib.file_digest(file, "sha256").hexdigest() != expected:
            raise ValueError(f"pinned file digest differs: {path}")


def _registry_snapshot() -> dict:
    if not MAIN_REGISTRY.is_file():
        raise ValueError("main seed registry is missing")
    fleet_registries = set()
    for pattern in ("*/seed_windows", "*/registry/seed_windows", "*/registry-pilot/seed_windows"):
        fleet_registries.update(FLEET.glob(pattern + ".json"))
        fleet_registries.update(path.with_suffix(".json") for path in FLEET.glob(pattern + ".d"))
    seed_api = runpy.run_path(str(GENERATOR_TREE / "server/shengji/seeds.py"))
    windows = {}
    for path in [MAIN_REGISTRY, *sorted(fleet_registries)]:
        registry = seed_api["load"](path)
        seed_api["require_disjoint"](registry, SEED, ROUNDS // 2, what="SZ3 filler")
        for entry in registry["windows"]:
            # Registries can copy the same reservation and its original name.
            windows.setdefault(entry["name"], entry)
    return {"schema": seed_api["SCHEMA"], "windows": list(windows.values())}


_INSPECT = """\
import runpy
import sys
from pathlib import Path

runner, native, *args = sys.argv[1:]
if "--inspect" not in args:
    raise SystemExit("inspect-only probe")
if runpy.run_path(runner)["main"](args) != 0:
    raise SystemExit("served inspector failed")
from shengji.engine import combos, fast, _fast
if not fast.HAVE_FAST or combos.decompose is not fast.decompose or Path(_fast.__file__) != Path(native):
    raise SystemExit("pinned compiled engine is not active")
"""


def prepare_generator(capture: Path) -> tuple[list[str], dict]:
    """Check the pinned producer and return its command and isolated seed registry."""
    tree = GENERATOR_TREE
    server = tree / "server"
    fly = tree / "fly.toml"
    runner = server / "scripts/y_trajectory.py"
    native_root = server / "shengji"
    if _checked_output(["/usr/bin/git", "rev-parse", "HEAD"], cwd=tree).strip() != SHA:
        raise ValueError("R55 generator checkout head differs")
    if _checked_output(["/usr/bin/git", "status", "--porcelain", "--untracked-files=all"], cwd=tree):
        raise ValueError("R55 generator checkout is dirty")
    _verify_file(fly, FLY_SHA)
    _verify_file(runner, RUNNER_SHA)
    for name, digest in NATIVE_PINS.items():
        _verify_file(native_root / name, digest)
    for name, digest in MODEL_PINS.items():
        _verify_file(MODELS / name, digest)
    registry = _registry_snapshot()
    args = ["--fly", str(fly), "--models", str(MODELS)]
    python = [str(PYTHON), "-I", "-B"]
    stdout = _checked_output([*python, "-c", _INSPECT, str(runner), str(native_root / ENGINE),
                             *args, "--seed-registry", str(MAIN_REGISTRY), "--inspect"], cwd=server)
    inspected = json.loads(stdout.splitlines()[-1])
    if (inspected.get("baseline"), inspected.get("candidate"), inspected.get("fly_sha256"),
        inspected.get("play_seconds"), inspected.get("bury_seconds")) != (POLICY, POLICY, FLY_SHA, 3, 3):
        raise ValueError("served trajectory inspect identity differs")
    command = [*python, str(runner), *args, "--seed-registry", str(capture / "seed_windows.json"),
               "--rounds", str(ROUNDS), "--seed", str(SEED), "--workers", str(WORKERS),
               "--out", str(capture / "store")]
    return command, registry


def _read_metadata(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or linked corpus metadata: {path.name}")
    with path.open("rb") as file:
        data = file.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"oversize corpus metadata: {path.name}")
    return data


def validate_completion(store: Path) -> None:
    """Check producer receipts and all published shard identities and sizes."""
    if store.is_symlink() or (store / "shards").is_symlink():
        raise ValueError("corpus directory is a symlink")
    manifest, run, runtime = (
        json.loads(_read_metadata(store / name, _METADATA_LIMIT))
        for name in ("manifest.json", "run.json", "runtime.json")
    )
    run_id, config, identity = (manifest[key] for key in ("run_id", "config", "identity"))
    if (manifest["schema"] != "shengji-trajectory-manifest-v1"
            or manifest["source"] != "trajectory" or manifest["record_schema"] != "shengji-decision-record-v1"
            or run["schema"] != "shengji-trajectory-run-v1"
            or runtime["schema"] != "shengji-trajectory-runtime-v1"
            or not re.fullmatch(rf"traj-s{SEED}-[0-9a-f]{{12}}", run_id)
            or config["run_id"] != run_id or run["run_id"] != run_id
            or run["identity"] != identity or run["config"] != config):
        raise ValueError("corpus run and completion identities differ")
    served_runtime = config["served_runtime"]
    if (config["policy"] != POLICY or config["seed0"] != SEED or config["round_mix"] != "sampled"
            or config["capture_served_budget"] is not True or config["cap"] != 256
            or config["explore_k"] != 0 or config["explore_rate"] != 0
            or config["knobs"] or config["widen"]
            or config["served_budgets"] != {"play_seconds": 3, "bury_seconds": 3,
                                            "wall_clock_dependent": True}
            or served_runtime["SHENGJI_Y_CAPTURE_FLY_SHA256"] != FLY_SHA
            or served_runtime["SHENGJI_Y_CAPTURE_RUNNER_SHA256"] != RUNNER_SHA
            or identity["git_sha"] != SHA or identity["git_dirty"] is not False
            or identity["fast_engine"] is not True or identity["fast_module_sha256_16"] != FAST_SHA[:16]):
        raise ValueError("corpus recipe differs from the pinned R55 generator")
    clusters = ROUNDS // 2
    window = manifest["seed_window"]
    if (manifest["seed0"] != SEED or manifest["rounds"] != ROUNDS
            or manifest["counts"]["rounds"] != ROUNDS or manifest["clusters"] != clusters
            or len(manifest["shards"]) != clusters or manifest["merged"] is not None
            or window["name"] != run_id or window["span"] != [SEED, SEED + clusters] or window["conflicts"]
            or window["purpose"] != "trajectory" or window["allow_seed_overlap"] is not False
            or window["seed0"] != SEED or window["clusters"] != clusters
            or runtime["workers"] != WORKERS or runtime["resume"] is not False or runtime["merge"] is not False
            or runtime["fast_engine"] is not True or runtime["require_voids"] is not True
            or runtime["clusters"] != {"requested": clusters, "reused": [],
                                       "generated": list(range(clusters)), "failed": []}):
        raise ValueError("corpus completion counts or reservation differ")
    for idx, shard in enumerate(manifest["shards"]):
        prefix = f"shards/cluster-{idx:06d}"
        if (shard["cluster"] != idx or shard["seed"] != SEED + idx
                or shard["path"] != prefix + ".jsonl" or shard["sidecar"] != prefix + ".json"
                or not _HEX_SHA.fullmatch(shard["sha256"])
                or type(shard["records"]) is not int or shard["records"] < 1):
            raise ValueError(f"corpus shard identity differs at cluster {idx}")
        path = store / shard["path"]
        if path.is_symlink() or not path.is_file() or path.stat().st_size != shard["bytes"] or shard["bytes"] < 1:
            raise ValueError(f"corpus shard size or file differs at cluster {idx}")
        sidecar = _read_metadata(store / shard["sidecar"], _SIDECAR_LIMIT)
        if hashlib.sha256(sidecar).hexdigest() != shard["sidecar_sha256"]:
            raise ValueError(f"corpus sidecar digest differs at cluster {idx}")
        side = json.loads(sidecar)
        fields = ("cluster", "seed", "path", "sha256", "bytes", "records")
        if (side["schema"] != "shengji-trajectory-shard-v1" or side["run_id"] != run_id
                or side["round_mix"] != "sampled" or side["counts"]["rounds"] != 2
                or any(side[key] != shard[key] for key in fields)):
            raise ValueError(f"corpus sidecar identity differs at cluster {idx}")
