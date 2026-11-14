"""pr_ship.sh stops at the first failing step and records the pushed head.

Each test builds a throwaway repository with a bare ``origin`` (a real push,
read back with ``git ls-remote``) and a stub ``gh`` first on PATH that logs
its arguments and copies any ``--body-file`` it is given.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pr_ship.sh"

GH_STUB = """#!/usr/bin/env bash
set -euo pipefail
log="$GH_STUB_DIR/calls.log"
printf '%s\\n' "$*" >>"$log"
if [ "$1 $2" = "pr view" ]; then
  if [ -n "${GH_STUB_PR:-}" ]; then echo "$GH_STUB_PR"; exit 0; fi
  echo "no pull requests found" >&2; exit 1
fi
prev=""
for arg in "$@"; do
  if [ "$prev" = "--body-file" ]; then cp "$arg" "$GH_STUB_DIR/$1-$2.body"; fi
  prev=$arg
done
echo "https://example.invalid/pull/7"
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path):
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    for key, value in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
        git(work, "config", key, value)
    (work / "shared.txt").write_text("base\n")
    git(work, "add", "shared.txt")
    git(work, "commit", "-q", "-m", "base")
    git(work, "remote", "add", "origin", str(origin))
    git(work, "push", "-q", "origin", "main")
    git(work, "switch", "-q", "-c", "topic")
    (work / "feature.txt").write_text("feature\n")
    git(work, "add", "feature.txt")
    git(work, "commit", "-q", "-m", "feature")

    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    gh = stub_dir / "gh"
    gh.write_text(GH_STUB)
    gh.chmod(0o755)
    body = tmp_path / "body.md"
    body.write_text("Does a thing.\n")
    env = {**os.environ, "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}", "GH_STUB_DIR": str(stub_dir),
           "PR_SHIP_GATES": "true", "GIT_TERMINAL_PROMPT": "0"}
    env.pop("GH_STUB_PR", None)

    class Repo:
        pass

    r = Repo()
    r.work, r.origin, r.stub, r.body, r.env = work, origin, stub_dir, body, env
    return r


def ship(r, *args: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=r.work, env={**r.env, **env},
                          capture_output=True, text=True)


def remote_head(r, branch: str = "topic") -> str:
    out = git(r.work, "ls-remote", "origin", f"refs/heads/{branch}")
    return out.split()[0] if out else ""


def gh_calls(r) -> str:
    log = r.stub / "calls.log"
    return log.read_text() if log.exists() else ""


def test_ships_and_the_body_names_the_pushed_head(repo):
    done = ship(repo, "--title", "A thing", "--body-file", str(repo.body))
    assert done.returncode == 0, done.stderr
    head = git(repo.work, "rev-parse", "HEAD")
    assert remote_head(repo) == head
    body = (repo.stub / "pr-create.body").read_text()
    assert f"Head: `{head}`" in body and body.startswith("Does a thing.")
    assert "pr create --head topic --base main --title A thing" in gh_calls(repo)


def test_head_placeholder_is_replaced(repo):
    repo.body.write_text("Ready at {{HEAD}}.\n")
    done = ship(repo, "--title", "A thing", "--body-file", str(repo.body))
    assert done.returncode == 0, done.stderr
    head = git(repo.work, "rev-parse", "HEAD")
    assert (repo.stub / "pr-create.body").read_text() == f"Ready at {head}.\n"


def test_existing_pr_gets_a_review_ask_comment_at_the_pushed_head(repo):
    done = ship(repo, "--update-comment", GH_STUB_PR="12")
    assert done.returncode == 0, done.stderr
    head = git(repo.work, "rev-parse", "HEAD")
    assert (repo.stub / "pr-comment.body").read_text() == f"Review ask at `{head}`.\n"
    assert "pr comment 12 --body-file" in gh_calls(repo)
    assert "pr create" not in gh_calls(repo)


def test_force_with_lease_replaces_the_remote_head_after_an_amend(repo):
    assert ship(repo, "--title", "t", "--body-file", str(repo.body)).returncode == 0
    git(repo.work, "commit", "-q", "--amend", "-m", "feature, amended")
    done = ship(repo, "--update-comment", GH_STUB_PR="12")
    assert done.returncode == 0, done.stderr
    assert remote_head(repo) == git(repo.work, "rev-parse", "HEAD")


def test_refuses_mid_rebase(repo):
    git(repo.work, "switch", "-q", "main")
    (repo.work / "shared.txt").write_text("main side\n")
    git(repo.work, "commit", "-q", "-am", "main change")
    git(repo.work, "push", "-q", "origin", "main")
    git(repo.work, "switch", "-q", "topic")
    (repo.work / "shared.txt").write_text("topic side\n")
    git(repo.work, "commit", "-q", "-am", "topic change")
    rebase = subprocess.run(["git", "rebase", "main"], cwd=repo.work, capture_output=True, text=True)
    assert rebase.returncode != 0
    done = ship(repo, "--title", "t", "--body-file", str(repo.body))
    assert done.returncode == 2
    assert "rebase-merge present" in done.stderr
    assert remote_head(repo) == "" and gh_calls(repo) == ""


def test_refuses_mid_merge(repo):
    merge_head = repo.work / git(repo.work, "rev-parse", "--git-path", "MERGE_HEAD")
    merge_head.write_text(git(repo.work, "rev-parse", "HEAD") + "\n")
    done = ship(repo, "--dry-run")
    assert done.returncode == 2 and "MERGE_HEAD present" in done.stderr


def test_refuses_a_dirty_tree(repo):
    (repo.work / "feature.txt").write_text("edited, not committed\n")
    done = ship(repo, "--title", "t", "--body-file", str(repo.body))
    assert done.returncode == 2 and "dirty" in done.stderr
    assert remote_head(repo) == "" and gh_calls(repo) == ""


def test_refuses_an_untracked_file(repo):
    (repo.work / "stray.txt").write_text("x\n")
    done = ship(repo, "--dry-run")
    assert done.returncode == 2 and "stray.txt" in done.stderr


def test_a_rebase_conflict_stops_before_the_push(repo):
    git(repo.work, "switch", "-q", "main")
    (repo.work / "shared.txt").write_text("main side\n")
    git(repo.work, "commit", "-q", "-am", "main change")
    git(repo.work, "push", "-q", "origin", "main")
    git(repo.work, "switch", "-q", "topic")
    (repo.work / "shared.txt").write_text("topic side\n")
    git(repo.work, "commit", "-q", "-am", "topic change")
    marker = repo.stub / "gates-ran"
    done = ship(repo, "--rebase", "--title", "t", "--body-file", str(repo.body),
                PR_SHIP_GATES=f"touch {marker}")
    assert done.returncode == 3, done.stderr
    assert "conflicting files:\nshared.txt" in done.stderr
    assert not marker.exists(), "gates ran mid-rebase"
    assert remote_head(repo) == ""
    assert "pr create" not in gh_calls(repo)


def test_a_clean_rebase_ships_the_rebased_head(repo):
    git(repo.work, "switch", "-q", "main")
    (repo.work / "other.txt").write_text("main side\n")
    git(repo.work, "add", "other.txt")
    git(repo.work, "commit", "-q", "-m", "main change")
    git(repo.work, "push", "-q", "origin", "main")
    git(repo.work, "switch", "-q", "topic")
    before = git(repo.work, "rev-parse", "HEAD")
    done = ship(repo, "--rebase", "--title", "t", "--body-file", str(repo.body))
    assert done.returncode == 0, done.stderr
    head = git(repo.work, "rev-parse", "HEAD")
    assert head != before and remote_head(repo) == head
    assert f"Head: `{head}`" in (repo.stub / "pr-create.body").read_text()


def test_failing_gates_stop_the_push(repo):
    done = ship(repo, "--title", "t", "--body-file", str(repo.body), PR_SHIP_GATES="exit 7")
    assert done.returncode == 4
    assert "gates rc=7" in done.stdout
    assert remote_head(repo) == ""
    assert "pr create" not in gh_calls(repo)


def test_a_new_pr_without_title_stops_before_gates_and_push(repo):
    marker = repo.stub / "gates-ran"
    done = ship(repo, "--body-file", str(repo.body), PR_SHIP_GATES=f"touch {marker}")
    assert done.returncode == 2 and "--title and --body-file are required" in done.stderr
    assert not marker.exists() and remote_head(repo) == ""


def test_dry_run_prints_steps_and_changes_nothing(repo):
    marker = repo.stub / "gates-ran"
    done = ship(repo, "--dry-run", "--rebase", PR_SHIP_GATES=f"touch {marker}")
    assert done.returncode == 0, done.stderr
    for step in ("git fetch", "git rebase origin/main", "gates:", "git push --force-with-lease=refs/heads/topic:"):
        assert step in done.stdout
    assert not marker.exists() and remote_head(repo) == "" and gh_calls(repo) == ""


def test_refuses_on_the_base_branch(repo):
    git(repo.work, "switch", "-q", "main")
    done = ship(repo, "--dry-run")
    assert done.returncode == 2 and "topic branch" in done.stderr


def test_never_posts_to_the_bus():
    text = SCRIPT.read_text()
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "agent-bus" not in code and "bus.sh" not in code


def test_default_gates_run_affected_tests_for_the_changed_paths(repo):
    env = {k: v for k, v in repo.env.items() if k != "PR_SHIP_GATES"}
    done = subprocess.run(["bash", str(SCRIPT), "--title", "t", "--body-file", str(repo.body)],
                          cwd=repo.work, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "affected_tests.py --repo" in done.stdout and "gates rc=0" in done.stdout
    assert remote_head(repo) == git(repo.work, "rev-parse", "HEAD")
