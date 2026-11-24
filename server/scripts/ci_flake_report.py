#!/usr/bin/env python3
"""Markdown report of CI tests that failed and then passed on the same commit.

Runs are compared only within one head sha, head branch and workflow.  A job
that failed and whose job of the same name passed in a later attempt or run of
that group recovered: the code did not change, so the outcome did.  Failed tests
are read from the failed job's log (pytest's ``FAILED <nodeid>`` summary lines).
A failed test is reported as passing on rerun only when the later successful
job's log names it PASSED; otherwise the recovery is reported for the job, with
the failed tests listed, because a ``-q`` log cannot show that the test ran.

A ``gh api`` call that fails is tried ``API_TRIES`` times with a growing
pause; a run whose jobs still cannot be read is left out of the comparison
and listed in the report as skipped, so one transient failure does not end
the report.

Failures on a sha that never ran again cannot be classified; they are counted
in a separate section so a test that fails on one commit and passes on the next
stays visible without being called a flake.

    ci_flake_report.py --days 7 [--repo owner/name] [--workflow "PR checks"]

The script only reads (``gh api``); it writes the report to stdout.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

DEFAULT_REPO = "jerryyyu/shengji"
PER_PAGE = 100
# pytest's short summary line: `FAILED tests/test_x.py::test_y[param] - message`,
# possibly behind a timestamp and a session prefix such as `[2.1] `.
FAILED_LINE = re.compile(r"(?:^|\s)(?:FAILED|ERROR) ((?:server/)?tests/[^\s:]+\.py::\S+)")

# a failing ``gh api`` call is tried this many times, pausing BACKOFF * 2**n
# seconds after the n-th failure
API_TRIES = 3
BACKOFF = 2.0

Api = Callable[[str], str]


def gh_api(path: str) -> str:
    """The body of a GET through the authenticated ``gh`` CLI."""
    return subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout


def retrying(api: Api, tries: int = API_TRIES, backoff: float = BACKOFF,
             sleep: Callable[[float], None] | None = None) -> Api:
    """``api`` tried up to ``tries`` times; the last failure is raised."""
    pause = sleep or (lambda seconds: time.sleep(seconds))

    def call(path: str) -> str:
        for n in range(tries):
            try:
                return api(path)
            except subprocess.CalledProcessError:
                if n == tries - 1:
                    raise
                pause(backoff * 2 ** n)
        raise AssertionError("unreachable")
    return call


@dataclass
class Job:
    run_id: int
    attempt: int
    name: str
    conclusion: str | None
    job_id: int
    started: str


@dataclass
class Flake:
    tests: dict = field(default_factory=lambda: defaultdict(list))  # test -> occurrences
    jobs: list = field(default_factory=list)  # recovered jobs, with failed tests not shown to rerun
    unrerun: dict = field(default_factory=lambda: defaultdict(list))  # test -> occurrences
    skipped: list = field(default_factory=list)  # runs whose jobs could not be read


def runs_since(api: Api, repo: str, since: datetime, workflow: str | None) -> list[dict]:
    out: list[dict] = []
    page = 1
    day = since.strftime("%Y-%m-%d")
    while True:
        body = json.loads(api(f"repos/{repo}/actions/runs?created=%3E%3D{day}&per_page={PER_PAGE}&page={page}"))
        batch = body.get("workflow_runs", [])
        out.extend(r for r in batch if _parse(r["created_at"]) >= since
                   and (workflow is None or r.get("name") == workflow))
        if len(batch) < PER_PAGE:
            return out
        page += 1


def jobs_of(api: Api, repo: str, run: dict) -> list[Job]:
    out = []
    for attempt in range(1, int(run.get("run_attempt") or 1) + 1):
        page = 1
        while True:
            body = json.loads(api(f"repos/{repo}/actions/runs/{run['id']}/attempts/{attempt}/jobs"
                                  f"?per_page={PER_PAGE}&page={page}"))
            batch = body.get("jobs", [])
            out.extend(Job(run["id"], attempt, j["name"], j.get("conclusion"), j["id"],
                           j.get("started_at") or run["created_at"]) for j in batch)
            if len(batch) < PER_PAGE:
                break
            page += 1
    return out


def failed_tests(log: str) -> list[str]:
    """The distinct test node ids a pytest log reports as failed, in order."""
    seen: dict[str, None] = {}
    for match in FAILED_LINE.finditer(log):
        nodeid = match.group(1)
        seen.setdefault(nodeid[len("server/"):] if nodeid.startswith("server/") else nodeid, None)
    return list(seen)


def passed_tests(log: str, nodeids: list[str]) -> set[str]:
    """The ``nodeids`` a pytest log reports as PASSED (``-v``/``-rA`` output); a ``-q`` log
    names no passing node, so its job's success says nothing about one test."""
    out = set()
    for node in nodeids:
        name = re.escape(node)
        if re.search(rf"(?:^|\s)(?:server/)?{name}\s+PASSED\b|PASSED (?:server/)?{name}(?:\s|$)", log, re.M):
            out.add(node)
    return out


def collect(api: Api, repo: str, runs: list[dict]) -> Flake:
    """Failures grouped by (head sha, head branch, workflow): a recovery counts only
    within one branch's runs of one workflow."""
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for run in runs:
        groups[(run["head_sha"], run.get("head_branch") or "?", run.get("name") or "?")].append(run)
    report = Flake()
    logs: dict[int, str] = {}

    def log_of(job_id: int) -> str:
        if job_id not in logs:
            logs[job_id] = api(f"repos/{repo}/actions/jobs/{job_id}/logs")
        return logs[job_id]

    for (sha, branch, workflow), group in sorted(groups.items()):
        if not any(r.get("conclusion") == "failure" or int(r.get("run_attempt") or 1) > 1 for r in group):
            continue
        jobs = []
        for run in group:
            try:
                jobs += jobs_of(api, repo, run)
            except subprocess.CalledProcessError as exc:
                report.skipped.append({"run": run["id"], "sha": sha, "branch": branch,
                                       "workflow": workflow, "error": _gh_error(exc)})
        jobs.sort(key=lambda j: (j.started, j.run_id, j.attempt))
        for i, job in enumerate(jobs):
            if job.conclusion != "failure":
                continue
            later = [j for j in jobs[i + 1:] if j.name == job.name and (j.run_id, j.attempt) != (job.run_id, job.attempt)]
            recovered = [j for j in later if j.conclusion == "success"]
            tests = failed_tests(log_of(job.job_id))
            seen = {"sha": sha, "branch": branch, "workflow": workflow, "job": job.name,
                    "run": job.run_id, "attempt": job.attempt, "when": job.started}
            if recovered:
                ran = set()
                for success in recovered:
                    if tests and ran != set(tests):
                        ran |= passed_tests(log_of(success.job_id), tests)
                for test in tests:
                    if test in ran:
                        report.tests[test].append(seen)
                unproven = [t for t in tests if t not in ran]
                if unproven or not tests:
                    report.jobs.append({**seen, "tests": unproven})
            elif not later:
                for test in tests:
                    report.unrerun[test].append(seen)
    return report


def markdown(report: Flake, *, days: int, runs: int, now: datetime, unrerun_rows: int = 25) -> str:
    lines = [f"# CI flake report: {days} days to {now:%Y-%m-%d %H:%M} UTC", "",
             f"{runs} workflow runs scanned. Runs are compared only within one head sha, head branch "
             f"and workflow.", ""]
    lines += ["## Tests that failed, then passed on the same sha, branch and workflow", "",
              "The later successful job's log names the test as PASSED.", ""]
    if report.tests:
        lines += ["| test | flakes | shas | branches | jobs | last seen |", "|---|---:|---:|---|---|---|"]
        for test, seen in sorted(report.tests.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            lines.append(_row(test, seen))
    else:
        lines.append("None.")
    lines += ["", "## Jobs that failed, then passed on the same sha, branch and workflow", "",
              "The job recovered; the later log does not show these failed tests running.", ""]
    if report.jobs:
        lines += ["| job | workflow | branch | sha | run | when | failed tests |", "|---|---|---|---|---|---|---|"]
        for seen in sorted(report.jobs, key=lambda s: (s["when"], s["job"])):
            tests = ", ".join(f"`{t}`" for t in seen["tests"]) or "none named"
            lines.append(f"| {seen['job']} | {seen['workflow']} | {seen['branch']} | {seen['sha'][:8]} | "
                         f"{seen['run']}#{seen['attempt']} | {seen['when'][:16]} | {tests} |")
    else:
        lines.append("None.")
    lines += ["", "## Failed on a sha that never ran that job again (not classified)", ""]
    if report.unrerun:
        lines += ["| test | failures | shas | branches | jobs | last seen |", "|---|---:|---:|---|---|---|"]
        ranked = sorted(report.unrerun.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        for test, seen in ranked[:unrerun_rows]:
            lines.append(_row(test, seen))
        if len(ranked) > unrerun_rows:
            lines += ["", f"{len(ranked) - unrerun_rows} more tests not shown (--unrerun-rows)."]
    else:
        lines.append("None.")
    if report.skipped:
        lines += ["", "## Runs skipped: their jobs could not be read", "",
                  "These runs are left out of every comparison above.", "",
                  "| run | workflow | branch | sha | error |", "|---|---|---|---|---|"]
        for seen in report.skipped:
            lines.append(f"| {seen['run']} | {seen['workflow']} | {seen['branch']} | {seen['sha'][:8]} | "
                         f"{seen['error']} |")
    return "\n".join(lines) + "\n"


def _gh_error(exc: subprocess.CalledProcessError) -> str:
    text = " ".join(str(exc.stderr or "").split())[:120].replace("|", "/")
    return f"gh exit {exc.returncode}" + (f": {text}" if text else "")


def _row(test: str, seen: list[dict]) -> str:
    branches = sorted({s["branch"] for s in seen})
    jobs = sorted({s["job"] for s in seen})
    return (f"| `{test}` | {len(seen)} | {len({s['sha'] for s in seen})} | {', '.join(branches)} | "
            f"{', '.join(jobs)} | {max(s['when'] for s in seen)[:16]} |")


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def main(argv: list[str] | None = None, api: Api = gh_api, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--workflow", default="PR checks", help="workflow name; '' for every workflow")
    parser.add_argument("--unrerun-rows", type=int, default=25, help="rows in the not-classified section")
    args = parser.parse_args(argv)
    now = now or datetime.now(timezone.utc)
    api = retrying(api)
    runs = runs_since(api, args.repo, now - timedelta(days=args.days), args.workflow or None)
    sys.stdout.write(markdown(collect(api, args.repo, runs), days=args.days, runs=len(runs), now=now,
                              unrerun_rows=args.unrerun_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
