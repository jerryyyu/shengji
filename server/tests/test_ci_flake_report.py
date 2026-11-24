"""`scripts/ci_flake_report.py` on recorded GitHub API responses.

The fixture holds two real `PR checks` runs, trimmed to the fields the script
reads: run 45102283018, whose `server (compiled, 1)` job failed in attempts 1
and 2 and passed in attempt 3 on the same sha, and run 45108202462 on `main`,
whose `server (compiled, 2)` job failed once and never ran again.  The successful
attempt's log is not recorded (an empty `-q` log), so it shows no test passing.
Synthetic runs cover same-head runs on other branches and in other workflows.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci_flake_report.py"
FIXTURE = Path(__file__).parent / "fixtures" / "ci_flake_report" / "recorded.json"
REPO = "jerryyyu/shengji"
NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)
REROOT = "tests/test_pv_reroot_lead.py::test_flag_off_release54_decides_as_main"

spec = importlib.util.spec_from_file_location("ci_flake_report", SCRIPT)
report = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = report  # its dataclasses resolve their module there
spec.loader.exec_module(report)


@pytest.fixture
def api():
    data = json.loads(FIXTURE.read_text())
    calls = []

    def fake(path: str) -> str:
        calls.append(path)
        prefix = f"repos/{REPO}/actions/"
        assert path.startswith(prefix), path
        rest = path[len(prefix):]
        if rest.startswith("runs?"):
            return json.dumps({"workflow_runs": data["runs"] if "page=1" in rest else []})
        if rest.startswith("runs/") and "/attempts/" in rest:
            run, _, attempt = rest.split("?")[0].split("/")[1:4]
            return json.dumps({"jobs": data["jobs"][f"{run}/{attempt}"] if "page=1" in rest else []})
        if rest.startswith("jobs/") and rest.endswith("/logs"):
            return data["logs"].get(rest.split("/")[1], "")
        raise AssertionError(path)

    fake.calls = calls
    return fake


def _run(api, *args):
    out = io.StringIO()
    with redirect_stdout(out):
        assert report.main(["--days", "7", *args], api=api, now=NOW) == 0
    return out.getvalue()


def _sections(text):
    flakes, rest = text.split("## Jobs that failed, then passed", 1)
    jobs, unrerun = rest.split("## Failed on a sha that never ran that job again", 1)
    return flakes, jobs, unrerun


def _cells(line):
    return [c.strip() for c in line.strip("|").split("|")]


def test_a_recovered_job_with_a_quiet_log_is_a_job_recovery_and_a_lone_failure_is_not(api):
    text = _run(api)
    flakes, jobs, unrerun = _sections(text)
    # the successful attempt-3 log does not show the failed node running
    assert REROOT not in flakes
    rows = [_cells(line) for line in jobs.splitlines() if REROOT in line]
    assert [r[:5] for r in rows] == [
        ["server (compiled, 1)", "PR checks", "claude/offline-rt4", "680b47b6", f"45102283018#{n}"] for n in (1, 2)]
    assert all(REROOT in r[6] for r in rows)
    lone = next(line for line in unrerun.splitlines() if REROOT in line)
    assert _cells(lone)[1:4] == ["1", "1", "main"]
    assert text.startswith("# CI flake report: 7 days to 2026-11-24 00:00 UTC")
    assert "2 workflow runs scanned" in text


def test_only_gets_are_made_and_logs_are_read_for_failed_and_recovering_jobs(api):
    _run(api)
    assert all("/logs" in p or "/jobs" in p or "runs?" in p for p in api.calls)
    data = json.loads(FIXTURE.read_text())
    recovering = next(j["id"] for j in data["jobs"]["45102283018/3"] if j["name"] == "server (compiled, 1)")
    assert sorted(p for p in api.calls if p.endswith("/logs")) == sorted(
        f"repos/{REPO}/actions/jobs/{job}/logs"
        for job in ("137457382140", "137465493624", "137475016591", str(recovering)))


def test_runs_of_another_workflow_are_skipped(api):
    text = _run(api, "--workflow", "Deploy")
    assert "0 workflow runs scanned" in text and REROOT not in text


SHA = "c" * 40
NODE = "tests/test_x.py::test_y"


def _synthetic(runs, logs):
    """A fake ``gh api`` over runs given as (id, branch, workflow, [(job id, name, conclusion)])."""
    body = [{"id": rid, "name": workflow, "head_sha": SHA, "head_branch": branch, "event": "pull_request",
             "conclusion": "failure" if any(c == "failure" for _, _, c in jobs) else "success",
             "created_at": f"2026-11-23T0{i}:00:00Z", "run_attempt": 1}
            for i, (rid, branch, workflow, jobs) in enumerate(runs)]
    jobs = {f"{rid}/1": [{"id": jid, "name": name, "conclusion": c, "started_at": f"2026-11-23T0{i}:00:00Z"}
                         for jid, name, c in js] for i, (rid, _, _, js) in enumerate(runs)}

    def fake(path):
        rest = path[len(f"repos/{REPO}/actions/"):]
        if rest.startswith("runs?"):
            return json.dumps({"workflow_runs": body if "page=1" in rest else []})
        if "/attempts/" in rest:
            run, _, attempt = rest.split("?")[0].split("/")[1:4]
            return json.dumps({"jobs": jobs[f"{run}/{attempt}"] if "page=1" in rest else []})
        return logs.get(rest.split("/")[1], "")
    return fake


FAILED_LOG = f"[1.1] FAILED {NODE} - AssertionError\n"


def test_a_same_head_success_on_another_branch_is_not_a_recovery():
    api = _synthetic([(1, "claude/a", "PR checks", [(11, "server (pure, 1)", "failure")]),
                      (2, "claude/b", "PR checks", [(21, "server (pure, 1)", "success")])],
                     {"11": FAILED_LOG, "21": f"{NODE} PASSED\n"})
    flakes, jobs, unrerun = _sections(_run(api, "--workflow", ""))
    assert NODE not in flakes and NODE not in jobs and "claude/b" not in jobs + flakes
    assert _cells(next(line for line in unrerun.splitlines() if NODE in line))[1:4] == ["1", "1", "claude/a"]


def test_a_same_head_success_in_another_workflow_is_not_a_recovery():
    api = _synthetic([(1, "claude/a", "PR checks", [(11, "server (pure, 1)", "failure")]),
                      (2, "claude/a", "Nightly", [(21, "server (pure, 1)", "success")])],
                     {"11": FAILED_LOG, "21": f"{NODE} PASSED\n"})
    flakes, jobs, unrerun = _sections(_run(api, "--workflow", ""))
    assert NODE not in flakes and NODE not in jobs and NODE in unrerun


def test_a_test_counts_as_passing_on_rerun_only_when_the_later_log_shows_it_passed():
    runs = [(1, "claude/a", "PR checks", [(11, "server (pure, 1)", "failure")]),
            (2, "claude/a", "PR checks", [(21, "server (pure, 1)", "success")])]
    shown = _synthetic(runs, {"11": FAILED_LOG, "21": f"[1.1] {NODE} PASSED [ 50%]\n"})
    flakes, jobs, _ = _sections(_run(shown, "--workflow", ""))
    assert _cells(next(line for line in flakes.splitlines() if NODE in line))[1:4] == ["1", "1", "claude/a"]
    assert NODE not in jobs
    quiet = _synthetic(runs, {"11": FAILED_LOG, "21": "[1.1] 12 passed in 3.0s\n"})
    flakes, jobs, _ = _sections(_run(quiet, "--workflow", ""))
    assert NODE not in flakes
    assert _cells(next(line for line in jobs.splitlines() if NODE in line))[:3] == ["server (pure, 1)", "PR checks", "claude/a"]


@pytest.mark.parametrize("log, expected", [
    ("2026-11-23T03:16:54Z [1.1] FAILED tests/test_a.py::test_x[p-1] - AssertionError: boom\n", ["tests/test_a.py::test_x[p-1]"]),
    ("FAILED server/tests/test_a.py::test_x\nERROR tests/test_b.py::test_y - fixture\nFAILED tests/test_a.py::test_x\n",
     ["tests/test_a.py::test_x", "tests/test_b.py::test_y"]),
    ("tests/test_a.py::test_x PASSED\n1 failed\n", []),
])
def test_failed_tests_reads_pytest_summary_lines(log, expected):
    assert report.failed_tests(log) == expected


def test_the_unclassified_section_is_capped():
    flake = report.Flake()
    seen = {"sha": "a" * 40, "branch": "b", "job": "j", "run": 1, "attempt": 1, "when": "2026-11-23T00:00:00Z"}
    for i in range(3):
        flake.unrerun[f"tests/test_{i}.py::t"].append(seen)
    text = report.markdown(flake, days=1, runs=1, now=NOW, unrerun_rows=2)
    assert "1 more tests not shown" in text and "tests/test_2.py::t" not in text


def _failing(api, bad, failures):
    """``api`` with the first ``failures`` calls of each path containing ``bad`` exiting 1."""
    import subprocess

    left = {}

    def fake(path):
        if bad in path:
            left.setdefault(path, failures)
            if left[path] > 0:
                left[path] -= 1
                raise subprocess.CalledProcessError(1, ["gh", "api", path], stderr="HTTP 502: Bad Gateway")
        return api(path)
    return fake


def test_a_transient_gh_failure_is_retried(api, monkeypatch):
    pauses = []
    monkeypatch.setattr(report.time, "sleep", pauses.append)
    clean = _run(api)
    flaky = _run(_failing(api, "/attempts/2/jobs", report.API_TRIES - 1))
    assert flaky == clean
    assert pauses == [report.BACKOFF * 2 ** n for n in range(report.API_TRIES - 1)]


def test_a_run_whose_jobs_never_load_is_skipped_with_a_note(api, monkeypatch):
    monkeypatch.setattr(report.time, "sleep", lambda _: None)
    text = _run(_failing(api, "runs/45102283018/attempts/2/jobs", report.API_TRIES))
    skipped = text.split("## Runs skipped: their jobs could not be read", 1)[1]
    row = next(line for line in skipped.splitlines() if "45102283018" in line)
    assert _cells(row)[:4] == ["45102283018", "PR checks", "claude/offline-rt4", "680b47b6"]
    assert "gh exit 1" in row and "Bad Gateway" in row
    _, jobs, _ = _sections(text.split("## Runs skipped", 1)[0])
    assert "45102283018" not in jobs        # nothing from the unread run is compared
    assert "## Runs skipped" not in _run(api)
