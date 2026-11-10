"""deploy_web_only.sh on a scratch git repo, with fly and curl replaced by PATH stubs.

No network and no flyctl: the stub fly answers releases/machines from files and,
for `fly deploy`, copies the site's `after/` files over the live ones.
"""
import json
import os
import shutil
import shlex
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deploy_web_only.sh"
BASH = shutil.which("bash")

FAKE_FLY = r"""#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "$FAKE_SITE/fly.log"
case "$1" in
  releases) cat "$FAKE_SITE/releases.json" ;;
  machines) cat "$FAKE_SITE/machines.json" ;;
  deploy)
    test -n "${FAKE_DEPLOY_OK:-}" || exit 99
    pwd > "$FAKE_SITE/deploy_cwd"
    cp -R "$FAKE_SITE/after/." "$FAKE_SITE/" ;;
  *) exit 98 ;;
esac
"""

FAKE_CURL = r"""#!/usr/bin/env bash
set -euo pipefail
url="${@: -1}"
path="/${url#*://*/}"
[ "$url" = "${url#*://*/}" ] && path=/
case "$path" in
  /) file="$FAKE_SITE/index.html" ;;
  /healthz) file="$FAKE_SITE/healthz.json" ;;
  *) file="$FAKE_SITE$path" ;;
esac
[ -f "$file" ] || exit 22
cat "$file"
"""

IDENTITY = {"bot": "pv-search-r51", "fast": True,
            "prior": {"sha256": "0d17fd03" * 8, "threshold": 1, "top": 3},
            "pv_search": {"sha256": "f4f4127e" * 8, "worlds": 8, "candidates": 8,
                          "budget_seconds": "1.0", "bury_arm": "heuristic",
                          "bury_budget_seconds": None,
                          "latency_switches": {"single_candidate_fast": False}}}


def _git(cwd, *args, env=None):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, text=True,
                          capture_output=True, env=env).stdout.strip()


def _write(root: Path, rel: str, text: str):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def env(tmp_path):
    e = os.environ.copy()
    e.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
             GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
             GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com",
             DEPLOY_WEB_HEALTHZ_WAIT="0")
    return e


@pytest.fixture
def repo(tmp_path, env):
    """origin (bare) with main two commits ahead of the served commit: one in web/
    (edit, delete, add) and one in server/ that must not ship."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True, env=env)
    work = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True, env=env)
    _git(work, "remote", "add", "origin", str(origin), env=env)
    _write(work, "server/app.py", "served = True\n")
    _write(work, "fly.toml", "app = 'shengji'\n")
    _write(work, "Dockerfile", "FROM scratch\n")
    _write(work, "web/src/App.tsx", "old ui\n")
    _write(work, "web/src/gone.tsx", "removed upstream\n")
    _git(work, "add", "-A", env=env)
    _git(work, "commit", "-q", "-m", "served release", env=env)
    served = _git(work, "rev-parse", "HEAD", env=env)
    _write(work, "web/src/App.tsx", "new ui PHONE_MARKER\n")
    (work / "web/src/gone.tsx").unlink()
    _write(work, "web/src/added.tsx", "added upstream\n")
    _git(work, "add", "-A", env=env)
    _git(work, "commit", "-q", "-m", "web change", env=env)
    _write(work, "server/app.py", "served = False  # unscreened bot path\n")
    _git(work, "commit", "-q", "-am", "unscreened server change", env=env)
    _git(work, "push", "-q", "origin", "main", env=env)
    return {"work": work, "origin": origin, "served": served,
            "main": _git(work, "rev-parse", "HEAD", env=env)}


def _call(fn, *args, env):
    return subprocess.run(
        [BASH, "-c", f'source "{SCRIPT}"; {fn} "$@"', "_", *map(str, args)],
        text=True, capture_output=True, env=env)


def _build(repo, tmp_path, env):
    wt = tmp_path / "wt"
    r = _call("build_deploy_tree", repo["work"], repo["served"], repo["main"], wt,
              "claude/deploy-test", env=env)
    assert r.returncode == 0, r.stderr
    return wt, r.stdout.strip()


def test_build_takes_only_web_from_the_web_ref(repo, tmp_path, env):
    wt, deploy = _build(repo, tmp_path, env)
    assert (wt / "server/app.py").read_text() == "served = True\n"
    assert (wt / "web/src/App.tsx").read_text() == "new ui PHONE_MARKER\n"
    assert not (wt / "web/src/gone.tsx").exists()
    assert (wt / "web/src/added.tsx").exists()
    assert _git(wt, "rev-parse", "HEAD^", env=env) == repo["served"]
    r = _call("check_deploy_tree", repo["work"], deploy, repo["served"], repo["main"], env=env)
    assert r.returncode == 0, r.stderr
    assert _call("check_clean_worktree", wt, env=env).returncode == 0


def test_check_refuses_a_change_outside_web(repo, tmp_path, env):
    wt, _ = _build(repo, tmp_path, env)
    _write(wt, "fly.toml", "app = 'shengji'\n[env]\n")
    _git(wt, "commit", "-q", "-am", "stray", env=env)
    deploy = _git(wt, "rev-parse", "HEAD", env=env)
    r = _call("check_deploy_tree", repo["work"], deploy, repo["served"], repo["main"], env=env)
    assert r.returncode != 0
    assert "fly.toml" in r.stderr


def test_check_refuses_web_that_differs_from_the_web_ref(repo, tmp_path, env):
    wt, _ = _build(repo, tmp_path, env)
    _write(wt, "web/src/App.tsx", "hand edit\n")
    _git(wt, "commit", "-q", "-am", "hand edit", env=env)
    deploy = _git(wt, "rev-parse", "HEAD", env=env)
    r = _call("check_deploy_tree", repo["work"], deploy, repo["served"], repo["main"], env=env)
    assert r.returncode != 0
    assert "web/ differs" in r.stderr


def test_check_refuses_the_web_ref_itself(repo, env):
    r = _call("check_deploy_tree", repo["work"], repo["main"], repo["served"], repo["main"], env=env)
    assert r.returncode != 0
    assert "server/app.py" in r.stderr


def test_dirty_worktree_is_refused(repo, tmp_path, env):
    wt, _ = _build(repo, tmp_path, env)
    _write(wt, "web/stray.txt", "untracked\n")
    r = _call("check_clean_worktree", wt, env=env)
    assert r.returncode != 0
    assert "stray.txt" in r.stderr


def test_build_refuses_when_web_is_unchanged(repo, tmp_path, env):
    r = _call("build_deploy_tree", repo["work"], repo["served"], repo["served"],
              tmp_path / "wt", "claude/deploy-same", env=env)
    assert r.returncode != 0
    assert "nothing to deploy" in r.stderr


def test_build_refuses_an_existing_worktree_path(repo, tmp_path, env):
    (tmp_path / "wt").mkdir()
    r = _call("build_deploy_tree", repo["work"], repo["served"], repo["main"],
              tmp_path / "wt", "claude/deploy-x", env=env)
    assert r.returncode != 0
    assert "already exists" in r.stderr


def _site(tmp_path, rooms=0, after_identity=None, after_marker=True):
    site = tmp_path / "site"
    (site / "assets").mkdir(parents=True)
    (site / "after" / "assets").mkdir(parents=True)
    (site / "healthz.json").write_text(json.dumps({"ok": True, "rooms": rooms, **IDENTITY}))
    (site / "index.html").write_text('<script type="module" src="/assets/index-old1.js"></script>')
    (site / "assets/index-old1.js").write_text("old bundle")
    (site / "releases.json").write_text(json.dumps([
        {"Version": 63, "ImageRef": "registry.fly.io/shengji:old"},
        {"Version": 62, "ImageRef": "registry.fly.io/shengji:older"}]))
    (site / "machines.json").write_text(json.dumps([{"id": "m1", "state": "started"}]))
    after = dict(IDENTITY, **(after_identity or {}))
    (site / "after/healthz.json").write_text(json.dumps({"ok": True, "rooms": 0, **after}))
    (site / "after/index.html").write_text('<script type="module" src="/assets/index-new2.js"></script>')
    (site / "after/assets/index-new2.js").write_text(
        "new bundle PHONE_MARKER" if after_marker else "new bundle")
    (site / "after/releases.json").write_text(json.dumps([
        {"Version": 64, "ImageRef": "registry.fly.io/shengji:new"},
        {"Version": 63, "ImageRef": "registry.fly.io/shengji:old"}]))
    return site


def _run(repo, tmp_path, env, site, *extra, deploy_ok=False):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("fly", FAKE_FLY), ("curl", FAKE_CURL)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    e = dict(env, FAKE_SITE=str(site), PATH=str(bin_dir) + os.pathsep + env["PATH"])
    if deploy_ok:
        e["FAKE_DEPLOY_OK"] = "1"
    receipt = tmp_path / "receipt.json"
    r = subprocess.run(
        [BASH, str(SCRIPT), "--repo", str(repo["work"]), "--served-sha", repo["served"][:10],
         "--web-ref", "origin/main", "--branch", "claude/deploy-web-test",
         "--worktree", str(tmp_path / "wt"), "--receipt", str(receipt), *extra],
        text=True, capture_output=True, env=e)
    data = json.loads(receipt.read_text()) if receipt.exists() else None
    log = (site / "fly.log").read_text() if (site / "fly.log").exists() else ""
    return r, data, log


def _remote_branches(repo, env):
    return _git(repo["origin"], "branch", "--list", env=env)


def test_dry_run_checks_everything_but_neither_pushes_nor_deploys(repo, tmp_path, env):
    site = _site(tmp_path)
    r, data, log = _run(repo, tmp_path, env, site, "--dry-run", "--marker", "PHONE_MARKER")
    assert r.returncode == 0, r.stderr
    assert "deploy" not in log.split()
    assert "claude/deploy-web-test" not in _remote_branches(repo, env)
    assert data["status"] == "dry-run-ok"
    assert data["served_sha"] == repo["served"]
    assert data["web_ref_sha"] == repo["main"]
    wt = tmp_path / "wt"
    assert data["tree_sha"] == _git(wt, "rev-parse", "HEAD^{tree}", env=env)
    assert data["healthz_before"]["bot"] == "pv-search-r51"
    assert data["healthz_after"] == data["healthz_before"]
    assert data["fly_version_before"] == data["fly_version_after"] == 63
    assert data["started_machines"] == 1
    assert data["marker_found"] is False
    assert shlex.split(data["rollback_command"]) == [
        "fly", "deploy", "--app", "shengji", "--ha=false", "--image",
        "registry.fly.io/shengji:old", "--config",
        str(tmp_path / "receipt.json.rollback.fly.toml")]
    assert not data["pushed"] and not data["fly_deploy_ran"]


def test_refuses_when_rooms_are_open(repo, tmp_path, env):
    site = _site(tmp_path, rooms=2)
    r, data, log = _run(repo, tmp_path, env, site, "--dry-run")
    assert r.returncode == 1
    assert "rooms = 2" in r.stderr
    assert data["status"].startswith("refused")
    assert "deploy" not in log.split()


def test_real_mode_requires_a_marker(repo, tmp_path, env):
    r, _, log = _run(repo, tmp_path, env, _site(tmp_path))
    assert r.returncode == 2
    assert "--marker" in r.stderr
    assert log == ""


def test_identity_change_refuses_and_prints_the_rollback(repo, tmp_path, env):
    site = _site(tmp_path, after_identity={"bot": "pv-search-unscreened"})
    r, data, log = _run(repo, tmp_path, env, site, "--marker", "PHONE_MARKER", deploy_ok=True)
    assert r.returncode == 1
    assert "identity changed" in r.stderr
    assert "fly deploy --app shengji --ha=false --image registry.fly.io/shengji:old" in r.stderr
    assert data["status"].startswith("refused")
    assert data["healthz_after"]["bot"] == "pv-search-unscreened"
    assert "deploy --ha=false -a shengji" in log
    assert log.count("deploy") == 1


def test_real_mode_with_stub_fly_pushes_deploys_and_records(repo, tmp_path, env):
    site = _site(tmp_path)
    r, data, log = _run(repo, tmp_path, env, site, "--marker", "PHONE_MARKER", deploy_ok=True)
    assert r.returncode == 0, r.stderr
    assert "claude/deploy-web-test" in _remote_branches(repo, env)
    assert (site / "deploy_cwd").read_text().strip() == str((tmp_path / "wt").resolve())
    assert data["status"] == "deployed"
    assert (data["fly_version_before"], data["fly_version_after"]) == (63, 64)
    assert data["fly_image_after"] == "registry.fly.io/shengji:new"
    assert data["marker_found"] is True
    assert data["bundles_before"] == ["/assets/index-old1.js"]
    assert data["bundles_after"] == ["/assets/index-new2.js"]


def test_real_mode_refuses_when_the_marker_is_not_served(repo, tmp_path, env):
    site = _site(tmp_path, after_marker=False)
    r, data, _ = _run(repo, tmp_path, env, site, "--marker", "PHONE_MARKER", deploy_ok=True)
    assert r.returncode == 1
    assert "lacks the marker" in r.stderr
    assert data["marker_found"] is False


@pytest.mark.parametrize("phase", ["before", "after"])
@pytest.mark.parametrize("bad", [
    {"rooms": 0},
    {"ok": False},
    {"fast": False},
    {"bot": ""},
    {"rooms": False},
    {"rooms": "0"},
    {"rooms": -1},
    {"prior": None},
    {"prior": {"error": "missing package"}},
    {"pv_search": {"sha256": "truncated"}},
])
def test_invalid_health_refuses_real_cli(repo, tmp_path, env, phase, bad):
    site = _site(tmp_path)
    path = site / ("healthz.json" if phase == "before" else "after/healthz.json")
    health = json.loads(path.read_text())
    if bad == {"rooms": 0}:
        health = bad
    else:
        health.update(bad)
    path.write_text(json.dumps(health))
    r, data, log = _run(repo, tmp_path, env, site, "--marker", "PHONE_MARKER", deploy_ok=True)
    assert r.returncode == 1, r.stderr
    assert data["status"].startswith("refused: invalid /healthz")
    assert data["fly_deploy_ran"] == (phase == "after")
    assert data["pushed"] == (phase == "after")
    assert ("claude/deploy-web-test" in _remote_branches(repo, env)) == (phase == "after")
    assert log.count("deploy --ha=false") == (1 if phase == "after" else 0)


def test_new_room_after_deploy_does_not_invalidate_identity(repo, tmp_path, env):
    site = _site(tmp_path)
    path = site / "after/healthz.json"
    health = json.loads(path.read_text())
    health["rooms"] = 1
    path.write_text(json.dumps(health))
    r, data, _ = _run(repo, tmp_path, env, site, "--marker", "PHONE_MARKER", deploy_ok=True)
    assert r.returncode == 0, r.stderr
    assert data["status"] == "deployed"


@pytest.mark.parametrize("section,key", [
    ("prior", "sha256"), ("prior", "threshold"), ("prior", "top"),
    ("pv_search", "sha256"), ("pv_search", "worlds"),
    ("pv_search", "candidates"), ("pv_search", "budget_seconds"),
    ("pv_search", "bury_arm"), ("pv_search", "bury_budget_seconds"),
    ("pv_search", "latency_switches"),
])
def test_identity_requires_each_package_field(env, section, key):
    health = json.loads(json.dumps({"ok": True, "rooms": 0, **IDENTITY}))
    del health[section][key]
    result = _call("healthz_identity", json.dumps(health), "before", env=env)
    assert result.returncode != 0


def test_rollback_command_uses_preserved_config_from_foreign_cwd(repo, tmp_path, env):
    root = tmp_path / "receipt space's"
    root.mkdir()
    site = _site(root)
    r, data, _ = _run(repo, root, env, site, "--marker", "PHONE_MARKER", deploy_ok=True)
    assert r.returncode == 0, r.stderr
    args = shlex.split(data["rollback_command"])
    config = Path(args[args.index("--config") + 1])
    expected = _git(repo["work"], "show", repo["served"] + ":fly.toml", env=env) + "\n"
    assert config.is_absolute() and config.read_text() == expected
    foreign = root / "foreign"
    foreign.mkdir()
    (foreign / "fly.toml").write_text("app = 'different'\n[env]\nBOT = 'candidate'\n")
    (root / "wt/fly.toml").write_text("app = 'modified-worktree'\n")
    stub = root / "bin/fly"
    stub.write_text("#!/usr/bin/env python3\nimport json, pathlib, sys\na=sys.argv[1:]\np=pathlib.Path(a[a.index('--config')+1])\nprint(json.dumps({'args':a,'config':p.read_text()}))\n")
    result = subprocess.run([BASH, "-c", data["rollback_command"]], cwd=foreign,
                            env=dict(env, PATH=str(root / "bin") + os.pathsep + env["PATH"]),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    recovered = json.loads(result.stdout)
    assert recovered["config"] == expected
    assert recovered["args"][recovered["args"].index("--image") + 1] == "registry.fly.io/shengji:old"


@pytest.mark.parametrize("missing", ["image", "config", "existing-snapshot"])
def test_missing_rollback_inputs_refuse_before_push_or_deploy(repo, tmp_path, env, missing):
    site = _site(tmp_path)
    if missing == "image":
        (site / "releases.json").write_text(json.dumps([{"Version": 63}]))
    elif missing == "config":
        _git(repo["work"], "rm", "fly.toml", env=env)
        _git(repo["work"], "commit", "-qm", "missing config", env=env)
        repo["served"] = _git(repo["work"], "rev-parse", "HEAD", env=env)
        _write(repo["work"], "web/src/App.tsx", "another web change\n")
        _git(repo["work"], "commit", "-qam", "web change", env=env)
        _git(repo["work"], "push", "-q", "origin", "main", env=env)
    else:
        (tmp_path / "receipt.json.rollback.fly.toml").write_text("do not overwrite\n")
    r, data, log = _run(repo, tmp_path, env, site, "--marker", "PHONE_MARKER", deploy_ok=True)
    assert r.returncode == 1, r.stderr
    assert "could not preserve" in data["status"]
    assert not data["pushed"] and not data["fly_deploy_ran"]
    assert "claude/deploy-web-test" not in _remote_branches(repo, env)
    assert "deploy --ha=false" not in log
    if missing == "existing-snapshot":
        assert (tmp_path / "receipt.json.rollback.fly.toml").read_text() == "do not overwrite\n"
