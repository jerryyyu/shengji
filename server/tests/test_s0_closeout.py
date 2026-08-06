"""Terminal S0 closeout is fail-closed and touches only exact services."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s0_closeout as CLOSEOUT  # noqa: E402


def packet_text(state="S0_COMPLETE_SELECT_NONE"):
    decision = ("PROMOTE mc-s0-report-lcb" if state == "S0_COMPLETE_PROMOTE"
                else "SELECT NONE; production remains mc-strong")
    lines = [
        f"STATE: {state}",
        "HEAD / origin / dirty: HEAD=frozen; origin/main=main; dirty=''",
    ]
    for phase in ("s0a", "s0b-lcb", "s0c-report-lcb"):
        manifests = "; ".join(
            f"path{i} sha256=digest{i}" for i in range(8))
        lines.extend((
            f"{phase} manifests (8/8): {manifests}",
            f"{phase} aggregate: path sha256=digest survivor='policy' promotion=False",
            f"{phase} coverage: records={{}}; seeds=1..2; flips=[0,1]; exact=true",
            (f"{phase} provenance: host=mini; python=3.14.6; "
             "compiled_binary_sha256=digest; "
             "within_phase=true; cross_phase=true; frozen_identity=true"),
            f"{phase} sampler counters: {{}}",
        ))
    lines.extend((
        "S0a effects:",
        "S0b allocation contrasts:",
        "  adaptive-report_uniform: +0.1 +/- 0.1 95%=[0, 0.2]",
        "  adaptive-random: +0.1 +/- 0.1 95%=[0, 0.2]",
        "S0c confirmation contrasts:",
        "  arm-reference: +0.1 +/- 0.1 95%=[0, 0.2]",
        "  arm-null: +0.1 +/- 0.1 95%=[0, 0.2]",
        "  null-reference: +0.0 +/- 0.1 95%=[-0.1, 0.1]",
        "S0c criteria: {}",
        f"Final production decision from registered rule: {decision}",
        "CALIB / REPORT: sealed and unscored; never consumed",
    ))
    return "\n".join(lines) + "\n"


def test_terminal_packet_bar_is_complete_and_state_bound():
    text = packet_text()
    assert CLOSEOUT.packet_phases(text) == [
        "s0a", "s0b-lcb", "s0c-report-lcb"]
    assert CLOSEOUT.packet_problems(
        text, "S0_COMPLETE_SELECT_NONE") == []

    broken = text.replace("CALIB / REPORT: sealed and unscored", "CALIB open")
    assert any("CALIB / REPORT" in problem for problem in
               CLOSEOUT.packet_problems(
                   broken, "S0_COMPLETE_SELECT_NONE"))
    assert any("packet STATE differs" in problem for problem in
               CLOSEOUT.packet_problems(text, "S0_COMPLETE_PROMOTE"))


def test_terminal_packet_cannot_skip_only_one_child_phase():
    text = packet_text()
    text = "\n".join(
        line for line in text.splitlines()
        if not line.startswith("s0c-report-lcb ")) + "\n"
    problems = CLOSEOUT.packet_problems(
        text, "S0_COMPLETE_SELECT_NONE")
    assert any("both S0b and S0c" in problem for problem in problems)


def test_promotion_requires_confirmation_and_all_manifest_hashes():
    no_children = "\n".join((
        "STATE: S0_COMPLETE_PROMOTE",
        "HEAD / origin / dirty: clean",
        "s0a manifests (8/8): missing hashes",
        "s0a aggregate: path sha256=digest survivor=None",
        "s0a coverage: exact=true",
        ("s0a provenance: host=mini python=3.14.6 "
         "compiled_binary_sha256=digest within_phase=true "
         "cross_phase=true frozen_identity=true"),
        "s0a sampler counters: {}",
        "S0a effects:",
        "S0b: NOT REACHED",
        "S0c: NOT REACHED",
        "Final production decision from registered rule: PROMOTE impossible",
        "CALIB / REPORT: sealed and unscored",
    )) + "\n"
    problems = CLOSEOUT.packet_problems(
        no_children, "S0_COMPLETE_PROMOTE")
    assert "PROMOTE is impossible without an S0c confirmation" in problems
    assert "s0a does not list eight manifest hashes" in problems


def test_fresh_packet_must_match_durable_bytes(tmp_path):
    server = tmp_path / "server"
    logs = server / "runs/logs"
    logs.mkdir(parents=True)
    state = {"status": "S0_COMPLETE_SELECT_NONE"}
    (logs / "s0_pipeline_supervisor.state.json").write_text(json.dumps(state))
    packet = logs / "s0-final-packet.txt"
    packet.write_text(packet_text())

    def matching_run(*_args, **_kwargs):
        return SimpleNamespace(stdout=packet.read_bytes())

    result = CLOSEOUT.verify_terminal_packet(
        server, server / ".venv/bin/python", packet,
        tmp_path / "s0_packet.py", run_command=matching_run)
    assert result["state"] == "S0_COMPLETE_SELECT_NONE"
    assert result["packet_sha256"] == \
        CLOSEOUT.sha256_bytes(packet.read_bytes())

    def drifted_run(*_args, **_kwargs):
        return SimpleNamespace(stdout=b"drift\n")

    with pytest.raises(RuntimeError, match="differs from durable"):
        CLOSEOUT.verify_terminal_packet(
            server, server / ".venv/bin/python", packet,
            tmp_path / "s0_packet.py", run_command=drifted_run)


def test_nonterminal_state_refuses_before_packet_execution(tmp_path):
    server = tmp_path / "server"
    logs = server / "runs/logs"
    logs.mkdir(parents=True)
    (logs / "s0_pipeline_supervisor.state.json").write_text(
        json.dumps({"status": "WAITING"}))
    (logs / "s0-final-packet.txt").write_text(packet_text())

    def forbidden_run(*_args, **_kwargs):
        raise AssertionError("packet verifier must not run before terminality")

    with pytest.raises(RuntimeError, match="not terminal"):
        CLOSEOUT.verify_terminal_packet(
            server, Path("python"), logs / "s0-final-packet.txt",
            Path("s0_packet.py"), run_command=forbidden_run)


def test_launchctl_cleanup_is_exact_and_ordered():
    phases = ["s0a", "s0b-lcb", "s0c-report-lcb"]
    labels = CLOSEOUT.expected_launchctl_labels(phases)
    assert len(labels) == 26
    assert "com.shengji.s0mini.s0b_lcb.7" in labels
    unknown = "com.shengji.s0mini.unrelated"
    loaded = {
        # Submitted workers are keep-alive too. The terminal packet has proved
        # this exact reached-phase label complete, so cleanup may kill a
        # collision-restart process rather than waiting for an idle-PID race.
        labels[0]: "777",
        labels[8]: "-",
        "com.shengji.s0mini.keepawake": "999",
        # The submitted supervisor is keep-alive. A terminal closeout must be
        # able to remove it even while it is running; only live workers block.
        "com.shengji.s0mini.supervisor": "888",
        unknown: "123",
    }

    def fake_run(command, **_kwargs):
        if command == ["launchctl", "list"]:
            rows = ["PID\tStatus\tLabel"]
            rows.extend(f"{pid}\t0\t{label}" for label, pid in loaded.items())
            return SimpleNamespace(stdout="\n".join(rows) + "\n")
        assert command[:2] == ["launchctl", "remove"]
        loaded.pop(command[2])
        return SimpleNamespace(stdout="")

    result = CLOSEOUT.cleanup_launchctl(
        labels,
        terminal_workers=CLOSEOUT.expected_worker_labels(phases),
        run_command=fake_run)
    assert result["removed"][-2:] == [
        "com.shengji.s0mini.keepawake",
        "com.shengji.s0mini.supervisor",
    ]
    assert loaded == {unknown: "123"}


def test_launchctl_cleanup_refuses_a_live_worker():
    labels = CLOSEOUT.expected_launchctl_labels(["s0a"])
    loaded = {labels[0]: "123"}

    def fake_run(command, **_kwargs):
        if command == ["launchctl", "list"]:
            return SimpleNamespace(
                stdout=f"PID\tStatus\tLabel\n123\t0\t{labels[0]}\n")
        raise AssertionError("active service must never be removed")

    with pytest.raises(RuntimeError, match="services are active"):
        CLOSEOUT.cleanup_launchctl(labels, run_command=fake_run)


def test_cli_cleanup_refuses_unreached_s0_worker(tmp_path):
    """The actual main() path scans beyond packet-derived cleanup labels."""
    server = tmp_path / "server"
    logs = server / "runs/logs"
    logs.mkdir(parents=True)
    (logs / "s0_pipeline_supervisor.state.json").write_text(
        json.dumps({"status": "S0_COMPLETE_SELECT_NONE"}))
    packet = logs / "s0-final-packet.txt"
    packet.write_text(packet_text())
    python = server / ".venv/bin/python"
    packet_script = tmp_path / "s0_packet.py"
    unexpected = "com.shengji.s0mini.s0c_adaptive_lcb.0"

    def fake_run(command, **_kwargs):
        if command and command[0] == str(python):
            return SimpleNamespace(stdout=packet.read_bytes())
        if command == ["launchctl", "list"]:
            return SimpleNamespace(
                stdout=("PID\tStatus\tLabel\n"
                        f"456\t0\t{unexpected}\n"))
        raise AssertionError(f"cleanup must refuse before mutation: {command}")

    with pytest.raises(RuntimeError, match="unexpected S0 worker services"):
        CLOSEOUT.main([
            "--server", str(server),
            "--python", str(python),
            "--packet", str(packet),
            "--packet-script", str(packet_script),
            "--cleanup-launchctl",
        ], run_command=fake_run)


def test_terminal_worker_authorization_cannot_escape_cleanup_scope():
    labels = CLOSEOUT.expected_launchctl_labels(["s0a"])
    with pytest.raises(ValueError, match="outside cleanup scope"):
        CLOSEOUT.cleanup_launchctl(
            labels, terminal_workers=["com.shengji.s0mini.s0c_unknown.0"],
            run_command=lambda *_args, **_kwargs: SimpleNamespace(
                stdout="PID\tStatus\tLabel\n"))


def test_service_phase_name_is_validated_before_cleanup():
    with pytest.raises(ValueError, match="unsafe S0 phase"):
        CLOSEOUT.expected_launchctl_labels(["../../unrelated"])
