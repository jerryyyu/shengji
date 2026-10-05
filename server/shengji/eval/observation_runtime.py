"""Import-only M9 runtime qualification; no launch, claims or model loading.

Use in a fresh, isolated Linux interpreter on the final staged source tree.
Caller authenticates this adapter/helpers before import and the manifest bytes
before verification. A successful fence is NOT RELEASE or a free-host check.
Future child dispatch must verify in the actual worker interpreter too.
"""
from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path
import sys

from . import runtime_fence
from .observation_lease import file_stamp


SCHEMA = "shengji-m9-runtime-v1"
PRELOAD_IMPORTS = (
    "shengji.eval.observation_admission",
    "shengji.eval.observation_queue",
    "scripts.tactical_report",
    "shengji.eval.observation_process",
    "shengji.eval.observation_recipe",
    "shengji.eval.observation_lease",
    "shengji.train.pv_search_policy",
    "shengji.train.policy_prior",
    "shengji.train.ballot_opportunity",
    "shengji.ai.cwv_numpy",
    "shengji.ai.cwv_prior_numpy",
    "shengji.ai.cwv_policy",
    # shared_evaluator imports this at factory time; legacy encoder identity
    # verification imports the compatibility helper on its fallback path.
    # Pin both before admission rather than discovering them after scoring.
    "shengji.ai.cwv_numpy_evaluator",
    "shengji.ai.cwv_encoder_compat",
    "shengji.ai.refusal",
    "encodings.cp437",
)
PANEL_PRELOAD_IMPORTS = PRELOAD_IMPORTS + (
    "shengji.eval.m9_panel_persistence",
    "shengji.eval.m9_panel_readout",
    "shengji.eval.m9_panel_recipe",
    "shengji.eval.m9_panel_inputs",
    "shengji.eval.m9_panel_execution",
)
READOUT_PRELOAD_IMPORTS = PANEL_PRELOAD_IMPORTS + (
    "shengji.eval.m9_panel_artifact_reader",
    "shengji.eval.m9_panel_publication",
    "shengji.luna.atomic_io",
)


def _profile_imports(profile):
    profiles = {"observation": PRELOAD_IMPORTS, "panel": PANEL_PRELOAD_IMPORTS,
                "panel-readout": READOUT_PRELOAD_IMPORTS}
    if type(profile) is not str or profile not in profiles:
        raise ValueError("explicit observation, panel or panel-readout runtime profile required")
    return profiles[profile]


ENVIRONMENT = {
    "SHENGJI_FAST": "1",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
}


def _environment():
    required = {key: os.environ.get(key) for key in ENVIRONMENT}
    if required != ENVIRONMENT:
        raise ValueError("M9 native-thread/locale environment mismatch")
    allowed = set(ENVIRONMENT)
    for key in os.environ:
        if key.startswith(("SHENGJI_", "PYTHON", "OMP_", "OPENBLAS_", "MKL_",
                           "VECLIB_", "NUMEXPR_", "LC_", "LD_", "DYLD_",
                           "BLIS_", "GOTO_", "KMP_")) and key not in allowed:
            raise ValueError("unapproved runtime override: " + key)
    return required


def source_stat_inventory(source):
    """Application/scripts only: never walk the checkout's venv or datasets."""
    root = _root(source)
    found = {}
    for name in ("shengji", "scripts"):
        folder = root / name
        if not folder.is_dir() or folder.is_symlink():
            raise ValueError("missing application source directory")
        for path in folder.rglob("*"):
            if path.is_symlink():
                raise ValueError("symlink in source inventory")
            if path.suffix == ".pyc":
                raise ValueError("stale source bytecode forbidden")
            if path.is_file() and path.suffix in {".py", ".so"}:
                found[path.relative_to(root).as_posix()] = file_stamp(path)
    return found


def _root(source):
    path = Path(source)
    if (not path.is_absolute() or ".." in path.parts or not path.is_dir()
            or any(p.is_symlink() for p in (path, *path.parents))):
        raise ValueError("canonical nonsymlink source directory required")
    return path


def _sha(path):
    before = file_stamp(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if file_stamp(path) != before:
        raise ValueError("file changed during runtime hash")
    return digest.hexdigest()


def _origins(source):
    found = {}
    for name, module in list(sys.modules.items()):
        if name == "torch" or name.startswith("torch."):
            raise ValueError("torch forbidden in M9 NumPy runtime")
        if (name != "shengji" and not name.startswith("shengji.")
                and not name.startswith("scripts.")):
            continue
        origin = getattr(module, "__file__", None)
        if type(origin) is not str:
            raise ValueError("application module has no file origin")
        path = Path(origin)
        if not path.is_absolute() or str(path.resolve(strict=True)) != origin:
            raise ValueError("application module origin is not canonical")
        file_stamp(path)
        try:
            relative = path.relative_to(source)
        except ValueError as exc:
            raise ValueError("application module escaped source") from exc
        if relative.parts[0] not in {"shengji", "scripts"} or path.suffix not in {".py", ".so"}:
            raise ValueError("application module outside source inventory")
        found[name] = (module, str(path))
    return found


def _routes(source):
    if not sys.platform.startswith("linux") or os.environ.get("SHENGJI_FAST") != "1":
        raise ValueError("Linux SHENGJI_FAST=1 required")
    if not sys.dont_write_bytecode:
        raise ValueError("bytecode writes must be disabled (-B)")
    if not sys.flags.isolated:
        raise ValueError("isolated interpreter required (-I)")
    _environment()
    _origins(source)
    fast = sys.modules.get("shengji.engine.fast")
    native = getattr(fast, "_fast", None)
    combos = sys.modules.get("shengji.engine.combos")
    rnd = sys.modules.get("shengji.engine.round")
    numpy_model = sys.modules.get("shengji.ai.cwv_numpy")
    if (not getattr(fast, "HAVE_FAST", False) or native is None
            or not callable(getattr(fast, "decompose", None))
            or getattr(combos, "decompose", None) is not getattr(fast, "decompose", None)
            or getattr(getattr(rnd, "Round", None), "play", None)
                is not getattr(native, "round_play", None)
            or not callable(getattr(native, "round_play", None))
            or not callable(getattr(numpy_model, "_native_erf", None))):
        raise ValueError("required native M9 routes unavailable")


def preload(source, *, profile="observation"):
    """Import exactly the M9 dependency surface without constructing a model."""
    imports = _profile_imports(profile)
    source = _root(source)
    if not sys.platform.startswith("linux") or os.environ.get("SHENGJI_FAST") != "1":
        raise ValueError("Linux SHENGJI_FAST=1 required")
    if not sys.dont_write_bytecode:
        raise ValueError("bytecode writes must be disabled (-B)")
    if not sys.flags.isolated:
        raise ValueError("isolated interpreter required (-I)")
    _environment()
    _origins(source)  # reject a foreign already-imported tree BEFORE imports
    # Staged source must contain no bytecode: -B alone prevents writes, not
    # reading stale pyc. External package caches are explicitly pinned below.
    source_stat_inventory(source)
    sys.path.insert(0, str(source))
    importlib.invalidate_caches()
    for name in imports:
        importlib.import_module(name)
    _routes(source)


def _dependencies(source):
    """Loaded external Python/extension origins AND existing bytecode caches."""
    paths = set()
    for module in list(sys.modules.values()):
        for field in ("__file__", "__cached__"):
            raw = getattr(module, field, None)
            if not isinstance(raw, str):
                continue
            path = Path(raw)
            if field == "__cached__" and not path.exists():
                continue
            if not path.is_absolute():
                raise ValueError("relative dependency origin")
            path = path.resolve(strict=True)
            if any(path.is_relative_to(source / name) for name in ("shengji", "scripts")):
                continue
            file_stamp(path)
            paths.add(str(path))
    return {p: file_stamp(Path(p)) for p in sorted(paths)}


def _mapped_source_coverage(source, inventory):
    """The generic fence excludes source-root maps; all must be pinned here.

    In particular, an interpreter/venv or an unlisted library inside the
    checkout must not disappear between the source and external inventories.
    Final staging uses an interpreter outside the application source root.
    """
    for raw in runtime_fence._maps_snapshot(Path("/proc/self/maps")):
        path = Path(raw)
        if path.is_relative_to(source) and path.relative_to(source).as_posix() not in inventory:
            raise ValueError("mapped source file outside application inventory")


def capture(source, *, profile="observation"):
    """One import-only capture on Linux; returns metadata, writes nothing."""
    imports = _profile_imports(profile)
    source = _root(source)
    before = source_stat_inventory(source)
    preload(source, profile=profile)
    origins = _origins(source)
    deps = _dependencies(source)
    source_files = {p: _sha(source / p) for p in sorted(before)}
    dependency_files = {p: _sha(Path(p)) for p in deps}
    external = runtime_fence.capture(source, list(imports))
    _mapped_source_coverage(source, before)
    if (source_stat_inventory(source) != before or _origins(source) != origins
            or _dependencies(source) != deps):
        raise ValueError("runtime changed during capture")
    return {"schema": SCHEMA, "source_root": str(source),
            "source_files": source_files, "dependency_files": dependency_files,
            "environment": _environment(),
            "module_origins": {name: path for name, (_, path) in origins.items()},
            "external_runtime": external}


class ObservationRuntime:
    """Hash once at admission; subsequent checks only compare identities/stats."""

    def __init__(self, manifest, *, profile="observation"):
        imports = _profile_imports(profile)
        if (type(manifest) is not dict or set(manifest) != {
                "schema", "source_root", "source_files", "dependency_files", "external_runtime",
                "environment", "module_origins"}
                or manifest["schema"] != SCHEMA):
            raise ValueError("M9 runtime manifest schema mismatch")
        self.source = _root(manifest["source_root"])
        if manifest["environment"] != _environment():
            raise ValueError("runtime manifest environment mismatch")
        external = manifest["external_runtime"]
        if (type(external) is not dict or external.get("source_root") != str(self.source)
                or external.get("imports") != list(imports)):
            raise ValueError("M9 runtime import/source binding mismatch")
        self.source_stamps = source_stat_inventory(self.source)
        declared = manifest["source_files"]
        if type(declared) is not dict or set(declared) != set(self.source_stamps):
            raise ValueError("source file set mismatch")
        # Authenticate all application code/native bytes BEFORE importing it.
        if any(_sha(self.source / p) != h for p, h in declared.items()):
            raise ValueError("source hash mismatch")
        preload(self.source, profile=profile)
        self.origins = _origins(self.source)
        if manifest["module_origins"] != {name: path for name, (_, path) in self.origins.items()}:
            raise ValueError("runtime module origin map mismatch")
        self.deps = _dependencies(self.source)
        declared_deps = manifest["dependency_files"]
        if type(declared_deps) is not dict or set(declared_deps) != set(self.deps):
            raise ValueError("dependency file set mismatch")
        if any(_sha(Path(p)) != h for p, h in declared_deps.items()):
            raise ValueError("dependency hash mismatch")
        self.external = runtime_fence.RuntimeFence(external, self.source)
        if not self.check():
            raise ValueError(f"runtime changed during admission: {self.last_failure}")

    def check(self):
        """Fail closed and retain the first mismatch without rehashing files.

        ``last_failure`` is diagnostic only: never adopt a changed inventory
        as a new baseline. Module replacements count even at the same path.
        """
        self.last_failure = None
        stage = "routes"
        try:
            _routes(self.source)
            stage = "mapped_source_coverage"
            _mapped_source_coverage(self.source, self.source_stamps)
            for stage, read, expected in (
                ("source", source_stat_inventory, self.source_stamps),
                ("module_origins", _origins, self.origins),
                ("dependencies", _dependencies, self.deps),
            ):
                current = read(self.source)
                if current != expected:
                    self.last_failure = {
                        "stage": stage,
                        "added": sorted(current.keys() - expected.keys()),
                        "removed": sorted(expected.keys() - current.keys()),
                        "changed": sorted(k for k in current.keys() & expected.keys()
                                          if current[k] != expected[k]),
                    }
                    return False
            stage = "external_runtime"
            if not self.external.check():
                self.last_failure = {"stage": stage}
                detail = getattr(self.external, "last_failure", None)
                if detail is not None:
                    self.last_failure["detail"] = detail
                return False
            return True
        except (OSError, ValueError, RuntimeError) as exc:
            self.last_failure = {"stage": stage, "error": str(exc),
                                 "error_type": type(exc).__name__}
            return False
