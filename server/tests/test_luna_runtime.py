"""Runtime attestation witnesses: stamp a dirty tree, refuse an impure engine."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from shengji.luna import runtime as runtime_module
from shengji.luna.transport import (
    CodexTurnTransportError, DISABLED_FEATURES, PINNED_CODEX_VERSION,
)


CATALOG = {"schema": "pt-luna-codex-tool-catalog-v1",
           "version": PINNED_CODEX_VERSION,
           "binary_sha256": "2" * 64,
           "disabled_features": list(DISABLED_FEATURES),
           "feature_catalog_sha256": "3" * 64}


def _fake_git(status: str):
    answers = {
        ("status", "--porcelain=v1", "--untracked-files=all"): status,
        ("rev-parse", "HEAD"): "a" * 40,
        ("rev-parse", "HEAD^{tree}"): "b" * 40,
    }
    return lambda _repo, *args: answers[args]


@pytest.mark.parametrize("status,dirty", [("", False), (" M server/x.py\n", True)])
def test_source_identity_stamps_git_state_instead_of_refusing(
        monkeypatch, status, dirty):
    monkeypatch.setattr(runtime_module, "_git", _fake_git(status))
    monkeypatch.setattr(runtime_module, "_boot_identity_bytes",
                        lambda: b"boot-session")
    monkeypatch.setattr(runtime_module, "attest_codex_runtime",
                        lambda _binary: dict(CATALOG))
    runtime = runtime_module.source_identity(Path("/usr/bin/true"))
    assert runtime["schema"] == runtime_module.RUNTIME_SCHEMA
    assert runtime["git_dirty"] is dirty
    assert runtime["execution_git"] == "a" * 40
    assert runtime["codex_tool_catalog"] == CATALOG
    assert set(runtime["sources"]) == set(runtime_module.SOURCE_PATHS)
    assert runtime["source_set_sha256"] == runtime_module._sha(
        runtime["sources"])
    assert runtime_module.source_identity(Path("/usr/bin/true")) == runtime


def test_source_identity_refuses_impure_engine_and_bad_codex(monkeypatch):
    monkeypatch.setattr(runtime_module, "_git", _fake_git(""))
    monkeypatch.setattr(runtime_module, "_boot_identity_bytes",
                        lambda: b"boot-session")
    monkeypatch.setattr(runtime_module, "attest_codex_runtime",
                        lambda _binary: dict(CATALOG))
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    with pytest.raises(runtime_module.RuntimeAttestationError,
                       match="pure engine"):
        runtime_module.source_identity(Path("/usr/bin/true"))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.setenv("SHENGJI_FAST", "1")
    with pytest.raises(runtime_module.RuntimeAttestationError,
                       match="pure engine"):
        runtime_module.source_identity(Path("/usr/bin/true"))
    monkeypatch.delenv("SHENGJI_FAST")

    def refuse(_binary):
        raise CodexTurnTransportError("Codex version is not pinned")

    monkeypatch.setattr(runtime_module, "attest_codex_runtime", refuse)
    with pytest.raises(runtime_module.RuntimeAttestationError,
                       match="Codex runtime refused"):
        runtime_module.source_identity(Path("/usr/bin/true"))


def test_rpc_concurrency_tracks_peak_and_refuses_underflow():
    tracker = runtime_module.RPCConcurrency()
    tracker.enter()
    tracker.enter()
    tracker.leave()
    assert (tracker.active, tracker.maximum) == (1, 2)
    with pytest.raises(runtime_module.RuntimeAttestationError,
                       match="reset while active"):
        tracker.reset_maximum()
    tracker.leave()
    tracker.reset_maximum()
    assert tracker.maximum == 0
    with pytest.raises(runtime_module.RuntimeAttestationError,
                       match="underflow"):
        tracker.leave()


def test_bound_source_paths_exist_in_repository():
    """Every hashed path must exist, or ``source_identity`` refuses at launch."""
    server = Path(__file__).resolve().parents[1]
    missing = [p for p in runtime_module.SOURCE_PATHS
               if not (server / p).is_file()]
    assert missing == [], missing


def test_source_identity_binds_engine_and_policy_dirt_distinctly(
        monkeypatch, tmp_path):
    """Dirt in the engine and dirt in the production policy must produce
    different identities from each other and from the clean tree, even though
    ``git_dirty`` is only a boolean.  (Codex #201 review.)"""
    import shutil
    server = Path(__file__).resolve().parents[1]
    scratch = tmp_path / "server"
    for rel in ("shengji/engine", "shengji/ai", "shengji/luna"):
        shutil.copytree(server / rel, scratch / rel,
                        ignore=shutil.ignore_patterns("__pycache__"))
    (scratch / "scripts").mkdir()
    shutil.copy(server / "scripts" / "luna.py", scratch / "scripts" / "luna.py")
    monkeypatch.setattr(runtime_module, "_server_root", lambda: scratch)
    monkeypatch.setattr(runtime_module, "_git", _fake_git(" M x"))
    monkeypatch.setattr(runtime_module, "_boot_identity_bytes",
                        lambda: b"boot")
    monkeypatch.setattr(runtime_module, "attest_codex_runtime",
                        lambda binary: CATALOG)

    clean = runtime_module.source_identity(Path("/usr/bin/true"))
    assert "shengji/engine/round.py" in clean["sources"]
    assert "shengji/ai/registry.py" in clean["sources"]

    engine_file = scratch / "shengji" / "engine" / "round.py"
    engine_file.write_text(engine_file.read_text() + "\n# dirt\n")
    engine_dirty = runtime_module.source_identity(Path("/usr/bin/true"))
    shutil.copy(server / "shengji" / "engine" / "round.py", engine_file)

    policy_file = scratch / "shengji" / "ai" / "registry.py"
    policy_file.write_text(policy_file.read_text() + "\n# dirt\n")
    policy_dirty = runtime_module.source_identity(Path("/usr/bin/true"))

    ids = {clean["source_set_sha256"], engine_dirty["source_set_sha256"],
           policy_dirty["source_set_sha256"]}
    assert len(ids) == 3
    assert {k for k in clean["sources"]
            if clean["sources"][k] != engine_dirty["sources"][k]} == {
                "shengji/engine/round.py"}
    assert {k for k in clean["sources"]
            if clean["sources"][k] != policy_dirty["sources"][k]} == {
                "shengji/ai/registry.py"}
