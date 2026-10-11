import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fetch_fly_logs.sh"
DELTA_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "production_log_delta.py"
DELTA_SPEC = importlib.util.spec_from_file_location("production_log_delta", DELTA_SCRIPT)
assert DELTA_SPEC and DELTA_SPEC.loader
delta = importlib.util.module_from_spec(DELTA_SPEC)
DELTA_SPEC.loader.exec_module(delta)


def _fake_fly(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fly = bin_dir / "fly"
    fly.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "if test \"$1\" = ssh && test \"$2\" = console; then\n"
        "  ls -1 \"$FAKE_FLY_REMOTE\"\n"
        "elif test \"$1\" = ssh && test \"$2\" = sftp "
        "&& test \"$3\" = get; then\n"
        "  cp \"$FAKE_FLY_REMOTE/$(basename \"$4\")\" \"$5\"\n"
        "else\n"
        "  exit 97\n"
        "fi\n")
    fly.chmod(0o755)
    return bin_dir


def _env(repo: Path, remote: Path, bin_dir: Path):
    env = os.environ.copy()
    env["SHENGJI_FETCH_REPO_ROOT"] = str(repo)
    env["FAKE_FLY_REMOTE"] = str(remote)
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    return env


def _line(**fields):
    return (json.dumps(fields, sort_keys=True) + "\n").encode()


def test_declaration_summary_keeps_commits_and_worker_completions_separate():
    report = delta.summarize([
        {"e": "declare_decision", "bot": True, "record": {
            "schema": "pv-value-declare-decision-v1", "policy": "recorded-release44",
            "evaluated": False, "fallback_reason": "error", "seconds": 0.2}},
        {"e": "declare_decision", "bot": True, "record": {"schema": "unknown"}},
        {"e": "declare_decision", "bot": False, "record": {}},
        {"e": "model_search", "phase": "declare", "event": "completed", "elapsed_seconds": 0.3},
        {"e": "model_search", "phase": "declare", "event": "completed", "elapsed_seconds": 0.5},
        {"e": "model_search", "phase": "play", "event": "completed", "elapsed_seconds": 9},
    ])["declaration"]
    assert report["committed_events"] == 2
    assert report["value_records"] == report["unknown_records"] == 1
    assert report["policy_counts"] == {"recorded-release44": 1}
    assert report["unknown_policy_records"] == 0
    assert report["fallback_reasons"] == {"error": 1}
    assert report["model_search_completed"] == 2
    assert report["model_search_seconds_p50"] == 0.4
    empty = delta.summarize([])["declaration"]
    assert empty["fallback_fraction"] is None
    assert empty["decision_seconds_p50"] is None


def test_fetch_stages_validates_backs_up_and_hashes(tmp_path):
    repo = tmp_path / "repo"
    (repo / "server" / "shengji").mkdir(parents=True)
    logs = repo / "logs"
    logs.mkdir()
    old_a = '{"t":1,"e":"round_start","round":1}\n'
    (logs / "A.jsonl").write_text(old_a)
    remote = tmp_path / "remote"
    remote.mkdir()
    appended = ('{"t":2,"e":"play","round":1,"bot":true,'
                '"decision":{"schema":"pv-search-decision-v1",'
                '"policy":"recorded-old-policy","seconds":0.2,'
                '"work_complete":true,"refusal_fallback_worlds":0}}\n')
    appended += json.dumps({"e": "declare_decision", "bot": True, "record": {
        "schema": "pv-value-declare-decision-v1", "policy": "recorded-release44",
        "evaluated": False, "fallback_reason": "hard_budget", "seconds": 0.1}}) + "\n"
    (remote / "A.jsonl").write_text(old_a + appended)
    (remote / "B.jsonl").write_text('{"t":3,"e":"round_start","round":2}\n')
    bin_dir = _fake_fly(tmp_path)

    result = subprocess.run(
        [str(SCRIPT)], env=_env(repo, remote, bin_dir), text=True,
        capture_output=True, check=True)

    assert "fetched=2 changed=2 unchanged=0" in result.stdout
    assert (logs / "A.jsonl").read_text() == old_a + appended
    assert (logs / "B.jsonl").read_text() == '{"t":3,"e":"round_start","round":2}\n'
    backups = list((logs / "archive").glob("pre-refresh-*/A.jsonl"))
    assert len(backups) == 1
    assert backups[0].read_text() == old_a
    manifests = list((logs / "manifests").glob("fly-*.sha256"))
    assert len(manifests) == 1
    text = manifests[0].read_text()
    assert "A.jsonl" in text and "B.jsonl" in text
    delta_lines = [line for line in result.stdout.splitlines()
                   if line.startswith("production_log_delta ")]
    assert len(delta_lines) == 2
    a_line = next(line for line in delta_lines if "file=A.jsonl" in line)
    assert "status=ok" in a_line
    report = json.loads(a_line.split(" report=", 1)[1])
    assert report["appended_events"] == 2
    assert report["decision_policy_counts"] == {"recorded-old-policy": 1}
    assert report["unknown_policy_plays"] == 0
    assert report["declaration"]["policy_counts"] == {"recorded-release44": 1}
    assert report["declaration"]["fallback_reasons"] == {"hard_budget": 1}


def test_invalid_later_download_publishes_nothing(tmp_path):
    repo = tmp_path / "repo"
    (repo / "server" / "shengji").mkdir(parents=True)
    logs = repo / "logs"
    logs.mkdir()
    old = '{"version":"old"}\n'
    (logs / "A.jsonl").write_text(old)
    remote = tmp_path / "remote"
    remote.mkdir()
    (remote / "A.jsonl").write_text('{"version":"would-change"}\n')
    (remote / "B.jsonl").write_text('{not-json}\n')
    bin_dir = _fake_fly(tmp_path)

    result = subprocess.run(
        [str(SCRIPT)], env=_env(repo, remote, bin_dir), text=True,
        capture_output=True)

    assert result.returncode != 0
    assert (logs / "A.jsonl").read_text() == old
    assert not (logs / "B.jsonl").exists()
    assert not (logs / "archive").exists()
    assert not (logs / "manifests").exists()


def test_rewritten_log_is_refreshed_but_delta_attribution_refuses(tmp_path):
    repo = tmp_path / "repo"
    (repo / "server" / "shengji").mkdir(parents=True)
    logs = repo / "logs"
    logs.mkdir()
    (logs / "A.jsonl").write_text('{"t":1,"e":"round_start","round":1}\n')
    remote = tmp_path / "remote"
    remote.mkdir()
    replacement = '{"t":2,"e":"round_start","round":2}\n'
    (remote / "A.jsonl").write_text(replacement)
    bin_dir = _fake_fly(tmp_path)

    result = subprocess.run(
        [str(SCRIPT)], env=_env(repo, remote, bin_dir), text=True,
        capture_output=True, check=True)

    assert (logs / "A.jsonl").read_text() == replacement
    assert "file=A.jsonl status=refused" in result.stderr
    backups = list((logs / "archive").glob("pre-refresh-*/A.jsonl"))
    assert len(backups) == 1
    assert backups[0].read_text() == '{"t":1,"e":"round_start","round":1}\n'


def test_delta_attributes_late_rows_to_recorded_policy_not_current_config(tmp_path):
    before = tmp_path / "before.jsonl"
    after = tmp_path / "after.jsonl"
    old = _line(t=1.0, e="round_start", round=7)
    appended = b"".join([
        _line(t=2.0, e="model_search", round=7, phase="play", event="completed",
              policy="old-policy", elapsed_seconds=0.2),
        _line(t=2.1, e="play", round=7, bot=True, cards=["S2"],
              decision={"schema": "pv-search-decision-v1", "policy": "old-policy",
                        "seconds": 0.21, "work_complete": True,
                        "refusal_fallback_worlds": 0}),
        _line(t=2.2, e="bot_timing", round=7, phase="play", acted=True,
              policy="old-policy", compute_seconds=0.22, turn_seconds=0.7),
    ])
    before.write_bytes(old)
    after.write_bytes(old + appended)

    report = delta.summarize(delta.appended_events(before, after))

    assert report["appended_events"] == 3
    assert report["decision_policy_counts"] == {"old-policy": 1}
    assert report["observed_event_policy_counts"] == {"old-policy": 3}
    assert report["unknown_policy_plays"] == 0
    assert report["search_fallbacks"] == 0
    assert report["latency_seconds_p50"] == {
        "decision": 0.21, "model_search_completed": 0.2,
        "bot_compute": 0.22, "turn": 0.7,
    }


def test_delta_refuses_rewritten_history(tmp_path):
    before = tmp_path / "before.jsonl"
    after = tmp_path / "after.jsonl"
    before.write_bytes(_line(t=1, e="play"))
    after.write_bytes(_line(t=1, e="round_start"))

    with pytest.raises(delta.DeltaError, match="exact prefix"):
        delta.appended_events(before, after)


def test_summary_exposes_unknown_policy_and_fallbacks():
    report = delta.summarize([
        {"t": 1, "e": "play", "round": 1, "bot": True,
         "decision": {"schema": "pv-search-fallback-v1", "work_complete": False,
                      "refusal_fallback_worlds": 4}},
    ])

    assert report["unknown_policy_plays"] == 1
    assert report["search_fallbacks"] == 1
    assert report["refusal_fallback_worlds"] == 4
    assert report["decision_policy_counts"] == {}
