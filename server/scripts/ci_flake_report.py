#!/usr/bin/env python3
"""Markdown report of CI tests that failed and then passed on the same commit.

A failure counts as a flake when a job failed in one workflow run (or run
attempt) and the job of the same name passed in a later attempt or a later run
of the same head sha: the code did not change, so the outcome did.  Failed
tests are read from the failed job's log (pytest's ``FAILED <nodeid>`` summary
lines); a flaky job whose log names no test is listed as a job-level flake.

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
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

DEFAULT_REPO = "jerryyyu/shengji"
PER_PAGE = 100
# pytest's short summary line: `FAILED tests/test_x.py::test_y[param] - message`,
# possibly behind a timestamp and a session prefix such as `[2.1] `.
FAILED_LINE = re.compile(r"(?:^|\s)(?:FAILED|ERROR) ((?:server/)?tests/[^\s:]+\.py::\S+)")

Api = Callable[[str], str]


def gh_api(path: str) -> str:
    """The body of a GET through the authenticated ``gh`` CLI."""
    return subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout


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
    jobs: list = field(default_factory=list)  # job-level flakes (no test named)
    unrerun: dict = field(default_factory=lambda: defaultdict(list))  # test -> occurrences


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


def collect(api: Api, repo: str, runs: list[dict]) -> Flake:
    by_sha: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        by_sha[run["head_sha"]].append(run)
    report = Flake()
    for sha, sha_runs in sorted(by_sha.items()):
        if not any(r.get("conclusion") == "failure" or int(r.get("run_attempt") or 1) > 1 for r in sha_runs):
            continue
        branch = sha_runs[0].get("head_branch") or "?"
        jobs = [job for run in sha_runs for job in jobs_of(api, repo, run)]
        jobs.sort(key=lambda j: (j.started, j.run_id, j.attempt))
        for i, job in enumerate(jobs):
            if job.conclusion != "failure":
                continue
            later = [j for j in jobs[i + 1:] if j.name == job.name and (j.run_id, j.attempt) != (job.run_id, job.attempt)]
            passed = any(j.conclusion == "success" for j in later)
            tests = failed_tests(api(f"repos/{repo}/actions/jobs/{job.job_id}/logs"))
            seen = {"sha": sha, "branch": branch, "job": job.name, "run": job.run_id,
                    "attempt": job.attempt, "when": job.started}
            if passed and tests:
                for test in tests:
                    report.tests[test].append(seen)
            elif passed:
                report.jobs.append(seen)
            elif not later:
                for test in tests:
                    report.unrerun[test].append(seen)
    return report


def markdown(report: Flake, *, days: int, runs: int, now: datetime, unrerun_rows: int = 25) -> str:
    lines = [f"# CI flake report: {days} days to {now:%Y-%m-%d %H:%M} UTC", "",
             f"{runs} workflow runs scanned. A flake is a failed job whose job of the same name passed "
             f"later on the same head sha.", ""]
    lines += ["## Tests that failed, then passed on the same sha", ""]
    if report.tests:
        lines += ["| test | flakes | shas | branches | jobs | last seen |", "|---|---:|---:|---|---|---|"]
        for test, seen in sorted(report.tests.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            lines.append(_row(test, seen))
    else:
        lines.append("None.")
    lines += ["", "## Jobs that failed with no test named, then passed on the same sha", ""]
    if report.jobs:
        lines += ["| job | branch | sha | run | when |", "|---|---|---|---|---|"]
        for seen in sorted(report.jobs, key=lambda s: s["when"]):
            lines.append(f"| {seen['job']} | {seen['branch']} | {seen['sha'][:8]} | "
                         f"{seen['run']}#{seen['attempt']} | {seen['when'][:16]} |")
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
    return "\n".join(lines) + "\n"


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
    runs = runs_since(api, args.repo, now - timedelta(days=args.days), args.workflow or None)
    sys.stdout.write(markdown(collect(api, args.repo, runs), days=args.days, runs=len(runs), now=now,
                              unrerun_rows=args.unrerun_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
