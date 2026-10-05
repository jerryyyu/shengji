"""Synthetic owner/lease witnesses; no experiment or actual child process."""
import hashlib
import json
from pathlib import Path

import pytest

from shengji.eval import observation_admission as admission
from test_observation_admission import _fixture


def _panel(tmp_path, monkeypatch):
    path, _, packet, paths = _fixture(tmp_path, monkeypatch)
    packet["schema"] = admission.PANEL_SCHEMA
    packet.pop("read_complete")
    packet["timeout_seconds"] = 901
    packet["process_timeout_seconds"] = 931
    # The panel uses the explicitly captured queue, not original M9's v49 gate.
    entry = packet["queue"]["reservations"][0]
    entry["lane"] = "completed-data"
    entry["terminal_suffix"] = "completed-data LANE DONE"
    predecessor = Path(entry["path"])
    record = json.loads(predecessor.read_text())
    record["lane"] = entry["lane"]
    predecessor.write_text(json.dumps(record))
    entry["sha256"] = hashlib.sha256(predecessor.read_bytes()).hexdigest()
    recipe = packet["recipe"]
    recipe["output_dir"] = recipe.pop("output")
    recipe.pop("timeout_seconds")
    saved = tmp_path / "already-read.json"
    saved.write_text('{"analysis":{}}')
    recipe["saved_readout"] = str(saved)
    recipe["saved_readout_sha256"] = hashlib.sha256(saved.read_bytes()).hexdigest()
    monkeypatch.setattr(admission, "validate_panel_recipe", lambda value: None)
    monkeypatch.setattr(admission, "build_panel_worker_command", lambda value, p, s: (
        value["python"], "-I", "-B",
        str(Path(value["source_root"]) / "server/scripts/observation_worker.py"),
        "--panel", "--packet", p, "--sha256", s))

    class Runtime:
        def __init__(self, manifest, *, profile):
            assert profile == "panel"
        def check(self):
            return True

    monkeypatch.setattr(admission, "ObservationRuntime", Runtime)
    calls = []
    monkeypatch.setattr(admission, "run_observation_process", lambda command, **kw:
                        (calls.append((command, kw)), {"status": "exited", "returncode": 0})[1])
    return path, packet, paths, calls


def _seal(path, packet, paths):
    raw = json.dumps(packet).encode()
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    paths["release"].write_text(json.dumps({
        "schema": "m9-panel-release-v1", "packet_sha256": digest}))
    return digest


def test_panel_owner_binds_namespace_directory_deadline_queue_and_drains(tmp_path, monkeypatch):
    path, packet, paths, calls = _panel(tmp_path, monkeypatch)
    digest = _seal(path, packet, paths)
    result = admission.run_panel_packet(path, digest)
    assert result["status"] == "exited"
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[-5:] == ("--panel", "--packet", str(path), "--sha256", digest)
    assert kwargs["timeout_seconds"] == 931
    claim = json.loads(paths["claim"].read_text())
    assert claim["schema"] == "m9-panel-owner-attempt-v1"
    assert claim["queue_snapshot"] == {"queue": "snapshot"}
    assert claim["inner_command"] == list(command)
    reservation = json.loads(paths["reservation"].read_text())
    assert reservation["schema"] == "codex-m9-panel-reservation-v1"
    assert reservation["lane"] == "m9-panel"
    assert reservation["count"] == 15
    assert reservation["output_root"] == str(paths["output"])
    assert not paths["host_lock"].exists()
    assert json.loads(paths["status"].read_text())["schema"] == "m9-panel-owner-terminal-v1"


@pytest.mark.parametrize("timeout", [True, 0, -1, 1.5, "901", None])
def test_panel_deadline_has_no_implicit_or_coerced_default(tmp_path, monkeypatch, timeout):
    path, packet, paths, calls = _panel(tmp_path, monkeypatch)
    packet["timeout_seconds"] = timeout
    with pytest.raises(ValueError, match="deadline"):
        admission.run_panel_packet(path, _seal(path, packet, paths))
    assert not calls and not paths["claim"].exists()


def test_default_owner_refuses_panel_schema(tmp_path, monkeypatch):
    path, packet, paths, calls = _panel(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="exact M9 packet"):
        admission.run_packet(path, _seal(path, packet, paths))
    assert not calls


def test_panel_owner_refuses_original_schema(tmp_path, monkeypatch):
    path, digest, _, paths = _fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="exact M9 packet"):
        admission.run_panel_packet(path, digest)
    assert not paths["claim"].exists()


@pytest.mark.parametrize("condition", ["saved_hash", "occupied", "hold", "release", "queue", "overlap"])
def test_panel_preclaim_gates_refuse_without_spending(tmp_path, monkeypatch, condition):
    path, packet, paths, calls = _panel(tmp_path, monkeypatch)
    if condition == "saved_hash":
        packet["recipe"]["saved_readout_sha256"] = "0" * 64
    elif condition == "occupied":
        paths["output"].mkdir()
    elif condition == "hold":
        paths["hold"].touch()
    elif condition == "overlap":
        packet["recipe"]["output_dir"] = packet["recipe"]["saved_readout"]
    elif condition == "queue":
        monkeypatch.setattr(admission.guards, "capture_queue", lambda spec:
                            (_ for _ in ()).throw(ValueError("live predecessor")))
    digest = _seal(path, packet, paths)
    if condition == "release":
        paths["release"].write_text("{}")
    with pytest.raises(ValueError):
        admission.run_panel_packet(path, digest)
    assert not calls and not paths["claim"].exists()


def test_ambiguous_post_child_drain_retains_panel_lease(tmp_path, monkeypatch):
    path, packet, paths, calls = _panel(tmp_path, monkeypatch)
    def census():
        if calls:
            raise ValueError("child still live")
    monkeypatch.setattr(admission, "_quiet_host", census)
    with pytest.raises(ValueError, match="child still live"):
        admission.run_panel_packet(path, _seal(path, packet, paths))
    assert len(calls) == 1
    assert paths["host_lock"].is_dir()
    assert paths["claim"].exists()
    assert not paths["status"].exists()


def test_original_release_namespace_cannot_authorize_panel(tmp_path, monkeypatch):
    path, packet, paths, calls = _panel(tmp_path, monkeypatch)
    digest = _seal(path, packet, paths)
    paths["release"].write_text(json.dumps({
        "schema": "m9-release-v1", "packet_sha256": digest}))
    with pytest.raises(ValueError, match="RELEASE"):
        admission.run_panel_packet(path, digest)
    assert not calls and not paths["claim"].exists()


@pytest.mark.parametrize("drift", [None, "hold", "peer_lock", "claim", "reservation", "status",
                                  "packet", "release", "owner", "queue", "dead_owner",
                                  "deadline", "bootstrap_deadline"])
def test_owner_to_child_real_control_files_and_queue(tmp_path, monkeypatch, drift):
    from types import SimpleNamespace
    from scripts import observation_worker as worker
    from shengji.eval import m9_panel_recipe

    # Preserve the real queue functions before the cheap owner fixture stubs them.
    capture = admission.guards.capture_queue
    unchanged = admission.guards.queue_unchanged
    path, packet, paths, _ = _panel(tmp_path, monkeypatch)
    monkeypatch.setattr(admission.guards, "capture_queue", capture)
    monkeypatch.setattr(admission.guards, "queue_unchanged", unchanged)
    entry = packet["queue"]["reservations"][0]
    Path(entry["status"]).write_text("2026-10-04T00:00:00Z completed-data LANE DONE\n")
    digest = _seal(path, packet, paths)
    monkeypatch.setattr(m9_panel_recipe, "validate_panel_recipe", lambda value: None)
    # Only relocate the hard-coded production lock for this local file witness.
    monkeypatch.setattr(worker, "Path", lambda value: paths["host_lock"]
                        if str(value) == "/root/.claude-host.lock" else Path(value))
    ticks = [1.0]
    monkeypatch.setattr(worker.time, "monotonic", lambda: ticks[0])
    def bootstrap(*args, **kwargs):
        # The inner clock includes this startup cost; it must not restart here.
        ticks[0] += packet["timeout_seconds"] + 10 if drift == "bootstrap_deadline" else 5
        return packet, paths["root"] / "server", {}
    monkeypatch.setattr(worker, "_bootstrap", bootstrap)
    seen = []
    child_errors = []

    def body(recipe, manifest, *, check_admission, check_budget):
        assert check_admission() is True
        check_budget()
        seen.append("body")
        if drift == "dead_owner":
            monkeypatch.setattr(worker.os, "kill", lambda *args:
                                (_ for _ in ()).throw(ProcessLookupError()))
        elif drift == "deadline":
            ticks[0] += packet["timeout_seconds"]
        elif drift:
            target = {"packet": path, "owner": paths["host_lock"] / "owner",
                      "queue": Path(entry["status"]),
                      "peer_lock": Path(packet["other_locks"][0])}.get(drift, paths.get(drift))
            target.write_text("changed")
        check_budget()
        assert check_admission() is True
        return {"synthetic": True}

    monkeypatch.setattr(worker, "_import_application", lambda *a, **kw: (
        m9_panel_recipe, SimpleNamespace(ENVIRONMENT=admission.ENVIRONMENT),
        admission.guards, None, SimpleNamespace(run_panel_body=body)))

    def child(command, **kwargs):
        outer_deadline = ticks[0] + kwargs["timeout_seconds"]
        try:
            worker.run_panel_packet(str(path), digest)
        except (ValueError, TimeoutError) as exc:
            child_errors.append(exc)
            if drift in {"deadline", "bootstrap_deadline"}:
                assert ticks[0] < outer_deadline  # Soft stop beats owner kill.
            raise
        return {"status": "exited", "returncode": 0}

    monkeypatch.setattr(admission, "run_observation_process", child)
    if drift:
        with pytest.raises((ValueError, TimeoutError)):
            admission.run_panel_packet(path, digest)
        expected = {
            "hold": "HOLD or peer lock", "claim": "panel claim changed",
            "peer_lock": "HOLD or peer lock",
            "reservation": "panel reservation changed", "status": "terminal status appeared",
            "packet": "panel packet changed", "release": "panel RELEASE changed",
            "owner": "panel host lease changed", "queue": "panel queue changed",
            "dead_owner": "panel owner process is stale", "deadline": "panel deadline exceeded",
            "bootstrap_deadline": "panel deadline exceeded",
        }[drift]
        assert len(child_errors) == 1 and expected in str(child_errors[0])
        assert paths["host_lock"].is_dir()  # Ambiguous child failure retains lease.
    else:
        admission.run_panel_packet(path, digest)
        assert not paths["host_lock"].exists()
    assert seen == ([] if drift == "bootstrap_deadline" else ["body"])


@pytest.mark.parametrize("outer", [True, 0, 900, 901, 901.5, None])
def test_panel_requires_explicit_outer_deadline_margin(tmp_path, monkeypatch, outer):
    path, packet, paths, calls = _panel(tmp_path, monkeypatch)
    packet["process_timeout_seconds"] = outer
    with pytest.raises(ValueError, match="process timeout"):
        admission.run_panel_packet(path, _seal(path, packet, paths))
    assert not calls and not paths["claim"].exists()
