"""Witness for scripts/safe_rm.py, the fleet cleanup delete tool.

Every case runs the script as a subprocess inside a private tmp tree, with HOME,
SAFE_RM_ROOTS, SAFE_RM_LAUNCHERS, SAFE_RM_PINS and SAFE_RM_KEEP pointed into that
tree, so no real path, keep file, launcher, packet or log is read or written.
"""

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "safe_rm.py"


@pytest.fixture
def world(tmp_path):
    w = Path(os.path.realpath(tmp_path))
    for d in ("root/ij-tree/server/.venv/bin", "root/gen-hybrid/server", "root/old-run",
              "fleet", "busy", "archive/pk", "home"):
        (w / d).mkdir(parents=True)
    (w / "root/gen-hybrid/server/.venv").symlink_to(w / "root/ij-tree/server/.venv")
    return w


def invocation(w, *args, processes=()):
    """Keep procfs integration checks on test-owned processes, not unrelated host services."""
    wrapper = w / "invoke.py"
    wrapper.write_text("""import glob, os, runpy, sys
original_glob = glob.glob
pids = [os.getpid()] + [int(p) for p in sys.argv[2].split(',') if p]
def controlled_glob(pattern, *args, **kwargs):
    if pattern == '/proc/[0-9]*':
        return [f'/proc/{pid}' for pid in pids]
    return original_glob(pattern, *args, **kwargs)
glob.glob = controlled_glob
script = sys.argv[1]
sys.argv = [script] + sys.argv[3:]
runpy.run_path(script, run_name='__main__')
""")
    return [sys.executable, str(wrapper), str(SCRIPT), ','.join(map(str, processes)), *map(str, args)]


def run(w, *args, home=None, processes=(), extra=None, timeout=300):
    env = dict(os.environ)
    env.update(
        HOME=str(home or w / "home"),
        SAFE_RM_ROOTS=str(w / "root"),
        SAFE_RM_LAUNCHERS=str(w / "fleet/*.sh"),
        SAFE_RM_PINS=f"{w}/archive/*/commands.json {w}/archive/*/SHA256SUMS",
        SAFE_RM_KEEP=str(w / "home/.safe_rm.keep"),
    )
    env.update(extra or {})
    p = subprocess.run(invocation(w, *args, processes=processes), env=env,
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout + p.stderr


def big_file(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(2_000_000))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_live_link_refuses(world):
    rc, out = run(world, world / "root/ij-tree")
    assert rc == 1 and "live-link" in out and (world / "root/ij-tree").is_dir()


def test_deletes_once_the_link_is_gone(world):
    (world / "root/gen-hybrid/server/.venv").unlink()
    rc, out = run(world, world / "root/ij-tree")
    assert rc == 0 and not (world / "root/ij-tree").exists()


def test_launcher_reference_refuses(world):
    (world / "fleet/claude_x.sh").write_text(f"PYM={world}/root/old-run/bin/python\n")
    rc, out = run(world, world / "root/old-run")
    assert rc == 1 and "referenced" in out and (world / "root/old-run").is_dir()


def test_in_use_cwd_refuses(world):
    sleeper = subprocess.Popen(["sleep", "60"], cwd=world / "busy")
    try:
        time.sleep(1)
        rc, out = run(world, world / "busy", processes=[sleeper.pid])
    finally:
        sleeper.kill()
        sleeper.wait()
    assert rc == 1 and "in-use" in out and (world / "busy").is_dir()


def test_protected_refuses(world):
    rc, out = run(world, "/")
    assert rc == 1 and "protected" in out


def test_dry_run_keeps(world):
    rc, out = run(world, "--dry-run", world / "root/old-run")
    assert rc == 0 and "WOULD DELETE" in out and (world / "root/old-run").is_dir()


def test_plain_delete(world):
    rc, out = run(world, world / "root/old-run")
    assert rc == 0 and not (world / "root/old-run").exists()


def test_hash_pinned_checkpoint_refuses(world):
    h = big_file(world / "root/mrt/p0/best.pt")
    (world / "archive/pk/commands.json").write_text(f'{{"init_sha256": "{h}"}}\n')
    rc, out = run(world, world / "root/mrt")
    assert rc == 1 and "pinned" in out and "sha256" in out
    assert (world / "root/mrt/p0/best.pt").is_file()


def test_path_pinned_folder_refuses(world):
    (world / "root/mrt/p0").mkdir(parents=True)
    (world / "archive/pk/commands.json").write_text(f'{{}}\n"{world}/root/mrt/p0/x.npz"\n')
    rc, out = run(world, world / "root/mrt")
    assert rc == 1 and "pinned" in out and "names" in out and (world / "root/mrt").is_dir()


def test_a_packets_own_sha256sums_does_not_pin_itself(world):
    pk = world / "archive/pk"
    (pk / "commands.json").write_text("{}\n")
    h = big_file(pk / "m.npz")
    (pk / "SHA256SUMS").write_text(f"{h}  m.npz\n")
    rc, out = run(world, pk)
    assert rc == 0 and not pk.exists()


def _small_pinned_home_relative(world, text):
    (world / "root/mrt/p0").mkdir(parents=True)
    (world / "root/mrt/p0/small.pt").write_text("small\n")
    (world / "archive/pk2").mkdir()
    (world / "archive/pk2/commands.json").write_text(text)


def test_tilde_path_refuses_below_hash_threshold(world):
    _small_pinned_home_relative(world, '{"x": "~/mrt/p0/small.pt"}\n')
    rc, out = run(world, world / "root/mrt", home=world / "root")
    assert rc == 1 and "names ~/mrt" in out and (world / "root/mrt/p0/small.pt").is_file()


def test_dollar_home_path_refuses(world):
    _small_pinned_home_relative(world, '{"x": "$HOME/mrt/p0/small.pt"}\n')
    rc, out = run(world, world / "root/mrt", home=world / "root")
    assert rc == 1 and "pinned" in out and (world / "root/mrt").is_dir()


def test_a_sibling_with_a_longer_name_does_not_pin(world):
    _small_pinned_home_relative(world, '{"x": "~/mrtx/other.pt"}\n')
    rc, out = run(world, "--dry-run", world / "root/mrt", home=world / "root")
    assert rc == 0 and "WOULD DELETE" in out and (world / "root/mrt").is_dir()


def test_deletes_once_unpinned(world):
    _small_pinned_home_relative(world, '{"x": "~/mrtx/other.pt"}\n')
    rc, out = run(world, world / "root/mrt")
    assert rc == 0 and not (world / "root/mrt").exists()


def _deep_sibling(world):
    pkt = world / "root/arch/pkt"
    (pkt / "data/ultra/s").mkdir(parents=True)
    (pkt / "data/ultra/s/f").write_text("x\n")
    (pkt / "views/u1/a/b/c/d").mkdir(parents=True)
    return pkt


def test_deep_sibling_link_refuses(world):
    pkt = _deep_sibling(world)
    (pkt / "views/u1/a/b/c/d/link").symlink_to(pkt / "data/ultra/s/f")
    rc, out = run(world, "--dry-run", pkt / "data/ultra")
    assert rc == 1 and "live-link" in out and (pkt / "data/ultra").is_dir()


def test_no_deep_link_would_delete(world):
    pkt = _deep_sibling(world)
    rc, out = run(world, "--dry-run", pkt / "data/ultra")
    assert rc == 0 and "WOULD DELETE" in out


def test_process_argument_containing_safe_rm_is_not_exempt(world):
    target = world / "root/old-run"
    marker = world / "trainer-ready"
    worker = subprocess.Popen([
        sys.executable, "-c",
        "import pathlib,sys,time; pathlib.Path(sys.argv[1]).touch(); time.sleep(60)",
        str(marker), "training_label=safe_rm", str(target),
    ], cwd=world / "busy")
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists() and worker.poll() is None
        rc, out = run(world, "--dry-run", target)
        assert rc == 1 and f"in-use pid {worker.pid}:" in out
        assert "WOULD DELETE" not in out and target.is_dir()
    finally:
        worker.terminate()
        worker.wait(timeout=5)


def test_launching_shell_with_the_path_in_its_argv_is_exempt(world):
    """A compound command keeps its shell alive with the target in argv; that ancestor is the caller, not a user."""
    target = world / "root/old-run"
    env = {**os.environ, "HOME": str(world / "home"), "SAFE_RM_ROOTS": str(world / "root"),
           "SAFE_RM_LAUNCHERS": str(world / "fleet/*.sh"),
           "SAFE_RM_PINS": f"{world}/archive/*/commands.json {world}/archive/*/SHA256SUMS",
           "SAFE_RM_KEEP": str(world / "home/.safe_rm.keep")}
    import shlex
    command = shlex.join(invocation(world, "--dry-run", target))
    out = subprocess.run(
        ["/bin/bash", "-c", command + '; echo "rc=$?"'],
        capture_output=True, text=True, env=env, cwd=world / "busy", timeout=120,
    ).stdout
    assert "WOULD DELETE" in out and "rc=0" in out and target.is_dir()


def test_a_non_ancestor_shell_naming_the_path_still_refuses(world):
    target = world / "root/old-run"
    marker = world / "shell-ready"
    holder = subprocess.Popen(
        ["/bin/bash", "-c", f'touch "{marker}"; sleep 60; echo "{target}" safe_rm.py'], cwd=world / "busy")
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        rc, out = run(world, "--dry-run", target)
        assert rc == 1 and f"in-use pid {holder.pid}:" in out and target.is_dir()
    finally:
        holder.terminate()
        holder.wait(timeout=5)


def test_ps_row_without_a_command_refuses_cli_dry_run(world, monkeypatch):
    """A pid/ppid-only row would skip the argv check for that process, so the inventory is not trusted."""
    if Path("/proc").is_dir():
        pytest.skip("the lsof stub stands in for macOS only")
    bin_dir = world / "bin"
    bin_dir.mkdir()
    for name, body in {"ps": 'echo "$PPID 1 python"; echo "999999 1"', "lsof": "printf 'p1\\nn/tmp\\n'"}.items():
        path = bin_dir / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    target = world / "root/old-run"
    rc, out = run(world, "--dry-run", target)
    assert rc == 1 and "ps malformed output" in out
    assert "WOULD DELETE" not in out and target.is_dir()


@pytest.mark.parametrize("tool", ["ps", "lsof"])
@pytest.mark.parametrize("mode", ["missing", "failed", "empty", "malformed"])
def test_unavailable_inventory_refuses_cli_dry_run(world, monkeypatch, tool, mode):
    if tool == "lsof" and Path("/proc").is_dir():
        pytest.skip("Linux uses procfs for cwd/exe inventory")
    bin_dir = world / "bin"
    bin_dir.mkdir()
    scripts = {"ps": 'echo "$PPID 1 python"', "lsof": "printf 'p1\\nn/tmp\\n'"}
    for name, body in scripts.items():
        if name == tool:
            if mode == "missing":
                continue
            body = {"failed": "exit 2", "empty": "exit 0", "malformed": "echo invalid"}[mode]
        path = bin_dir / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    target = world / "root/old-run"
    rc, out = run(world, "--dry-run", target)
    assert rc == 1 and "inventory unavailable" in out and tool in out
    assert "WOULD DELETE" not in out and target.is_dir()


@pytest.mark.parametrize("tool", ["ps", "lsof"])
def test_inventory_timeout_refuses_without_waiting_a_minute(monkeypatch, tool):
    import importlib.util
    spec = importlib.util.spec_from_file_location("safe_rm_timeout", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    observed = []

    def inventory(command, **kwargs):
        observed.append(command[0])
        assert kwargs["timeout"] == 60
        if command[0] == tool:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, f"{os.getpid()} 1 python\n", "")

    monkeypatch.setattr(mod.subprocess, "run", inventory)
    monkeypatch.setattr(mod.os.path, "isdir", lambda path: False)
    reasons = mod.in_use("/unused/target", "/unused/target")
    assert tool in observed
    assert any("inventory unavailable" in r and tool in r and "TimeoutExpired" in r for r in reasons)


@pytest.mark.parametrize("failure,refuses", [
    (PermissionError, True),    # unreadable live process: argv cannot establish its cwd
    (FileNotFoundError, False),  # exited process or kernel thread
    (OSError, True),             # any other procfs failure leaves the inventory untrusted
])
def test_procfs_inventory_refuses_unreadable_and_tolerates_exited(monkeypatch, failure, refuses):
    import importlib.util
    spec = importlib.util.spec_from_file_location("safe_rm_procfs", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "process_inventory", lambda command: (f"{os.getpid()} 1 python\n", None))
    monkeypatch.setattr(mod.os.path, "isdir", lambda path: True)
    monkeypatch.setattr(mod.glob, "glob", lambda pattern: ["/proc/123"])

    def readlink(path):
        raise failure(path)

    monkeypatch.setattr(mod.os, "readlink", readlink)
    reasons = mod.in_use("/unused/target", "/unused/target")
    if refuses:
        assert len(reasons) == 2 and all("inventory unavailable" in r for r in reasons)
    else:
        assert reasons == []


def test_unreadable_consumer_refuses_before_delete(world, monkeypatch, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("safe_rm_refusal", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("HOME", str(world / "home"))
    monkeypatch.setenv("SAFE_RM_ROOTS", str(world / "root"))
    monkeypatch.setenv("SAFE_RM_LAUNCHERS", str(world / "fleet/*.sh"))
    monkeypatch.setenv("SAFE_RM_PINS", str(world / "archive/*/commands.json"))
    monkeypatch.setenv("SAFE_RM_KEEP", str(world / "home/.safe_rm.keep"))
    monkeypatch.setattr(mod, "process_inventory", lambda cmd: (f"{os.getpid()} 1 python\n123 1 python worker.py\n", None))
    real_isdir, real_glob, real_readlink = mod.os.path.isdir, mod.glob.glob, mod.os.readlink
    monkeypatch.setattr(mod.os.path, "isdir", lambda p: True if p == "/proc" else real_isdir(p))
    monkeypatch.setattr(mod.glob, "glob", lambda p: ["/proc/123"] if p == "/proc/[0-9]*" else real_glob(p))

    def readlink(p, *args, **kwargs):
        if str(p).startswith("/proc/123/"):
            raise PermissionError(p)
        return real_readlink(p, *args, **kwargs)

    monkeypatch.setattr(mod.os, "readlink", readlink)
    target = world / "root/old-run"
    assert mod.main([str(target)]) == 1
    assert target.is_dir()
    out = capsys.readouterr().out
    assert "inventory unavailable" in out and "DELETED" not in out


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main",
                    "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True)


def _pin(world, h):
    (world / "archive/pk/commands.json").write_text(f'{{"init_sha256": "{h}"}}\n')


def _clone(world, at, push=True):
    """A clone at `at` (with its bare origin beside it) tracking models/m.npz; returns (clone, sha256)."""
    origin = at.parent / (at.name + "-origin.git")
    _git(at.parent, "init", "-q", "--bare", str(origin))
    _git(at.parent, "clone", "-q", str(origin), str(at))
    h = big_file(at / "models/m.npz")
    (at / ".gitignore").write_text("payload/\n")
    _git(at, "add", "models/m.npz", ".gitignore")
    _git(at, "commit", "-q", "-m", "m")
    if push:
        _git(at, "push", "-q", "origin", "HEAD:main")
        _git(at, "fetch", "-q", "origin")
    return at, h


def _linked_worktree(world, push=True):
    """A linked worktree under root/ whose common dir (the clone at world/main) is outside the target."""
    co, h = _clone(world, world / "main", push=push)
    wt = world / "root/wt"
    _git(co, "worktree", "add", "-q", "--detach", str(wt), "main")
    _pin(world, h)
    return co, wt, h


def test_healthy_linked_worktree_pin_is_exempt(world):
    _, wt, _ = _linked_worktree(world)
    rc, out = run(world, "--dry-run", wt)
    assert rc == 0 and "WOULD DELETE" in out
    assert "EXEMPT pin" in out and "models/m.npz" in out and "linked worktree" in out


def test_linked_worktree_on_an_unpushed_local_main_is_exempt(world):
    _, wt, _ = _linked_worktree(world, push=False)
    rc, out = run(world, "--dry-run", wt)
    assert rc == 0 and "EXEMPT pin" in out and "refs/heads/main" in out


def test_standalone_clone_with_its_only_origin_inside_the_target_refuses(world):
    box = world / "root/box"
    box.mkdir()
    co, h = _clone(world, box / "co")
    _pin(world, h)
    rc, out = run(world, "--dry-run", box)
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_standalone_clone_whose_origin_dropped_its_refs_refuses(world):
    co, h = _clone(world, world / "root/co")
    _git(world / "root/co-origin.git", "update-ref", "-d", "refs/heads/main")
    _pin(world, h)
    rc, out = run(world, "--dry-run", co)
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_linked_worktree_with_the_blob_missing_from_the_store_refuses(world):
    co, wt, _ = _linked_worktree(world)
    blob = subprocess.run(["git", "rev-parse", "HEAD:models/m.npz"], cwd=co, capture_output=True,
                          text=True, check=True).stdout.strip()
    (co / ".git/objects" / blob[:2] / blob[2:]).unlink()
    assert subprocess.run(["git", "cat-file", "-e", blob], cwd=co).returncode != 0
    rc, out = run(world, "--dry-run", wt)
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_linked_worktree_with_an_alternate_inside_the_target_refuses(world):
    co, wt, _ = _linked_worktree(world)
    (wt / "store").mkdir()
    (co / ".git/objects/info/alternates").write_text(f"{wt / 'store'}\n")
    rc, out = run(world, "--dry-run", wt)
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_modified_tracked_pin_refuses(world):
    _, wt, _ = _linked_worktree(world)
    _pin(world, big_file(wt / "models/m.npz"))
    rc, out = run(world, "--dry-run", wt)
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_untracked_pin_in_a_worktree_refuses(world):
    _, wt, _ = _linked_worktree(world)
    _pin(world, big_file(wt / "models/new.npz"))
    rc, out = run(world, "--dry-run", wt)
    assert rc == 1 and "models/new.npz" in out and "EXEMPT" not in out


def test_ignored_pin_in_a_worktree_refuses(world):
    _, wt, _ = _linked_worktree(world)
    _pin(world, big_file(wt / "payload/models/p.npz"))
    rc, out = run(world, "--dry-run", wt)
    assert rc == 1 and "payload/models/p.npz" in out and "EXEMPT" not in out


def test_tracked_pin_whose_commit_is_on_no_retained_ref_refuses(world):
    _, wt, _ = _linked_worktree(world)
    _git(wt, "switch", "-q", "-c", "topic")
    _pin(world, big_file(wt / "models/m.npz"))
    _git(wt, "commit", "-q", "-am", "local only")
    rc, out = run(world, "--dry-run", wt)
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_standalone_clone_subdirectory_keeps_its_pin(world):
    # the clone's .git survives this target, but its remote-tracking refs outlive the origin's own refs
    co, h = _clone(world, world / "root/co")
    _git(world / "root/co-origin.git", "update-ref", "-d", "refs/heads/main")
    _pin(world, h)
    rc, out = run(world, "--dry-run", co / "models")
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def _loose_blob(co):
    blob = subprocess.run(["git", "rev-parse", "HEAD:models/m.npz"], cwd=co, capture_output=True,
                          text=True, check=True).stdout.strip()
    path = co / ".git/objects" / blob[:2] / blob[2:]
    path.chmod(0o644)
    return blob, path


def _exists(co, blob):
    return subprocess.run(["git", "cat-file", "-e", blob], cwd=co).returncode == 0


def test_linked_worktree_with_a_corrupt_compressed_blob_refuses(world):
    co, wt, _ = _linked_worktree(world)
    blob, path = _loose_blob(co)
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) // 2])
    assert _exists(co, blob)
    rc, out = run(world, "--dry-run", wt)
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_linked_worktree_with_substituted_blob_bytes_refuses(world):
    import zlib
    co, wt, _ = _linked_worktree(world)
    blob, path = _loose_blob(co)
    size = (wt / "models/m.npz").stat().st_size
    path.write_bytes(zlib.compress(b"blob %d\0" % size + os.urandom(size)))
    assert _exists(co, blob)
    rc, out = run(world, "--dry-run", wt)
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_linked_worktree_with_a_loose_object_linked_into_the_target_refuses(world):
    co, wt, _ = _linked_worktree(world)
    blob, path = _loose_blob(co)
    moved = wt / "stash/obj"
    moved.parent.mkdir()
    path.rename(moved)
    path.symlink_to(moved)
    assert _exists(co, blob)
    rc, out = run(world, "--dry-run", wt)
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def _vaulted(world, vault=None):
    """root/run/best.pt pinned by sha256, with a byte-identical copy listed in the vault manifest."""
    vault = vault or world / "home/model-vault"
    h = big_file(world / "root/run/best.pt")
    (vault / "prod").mkdir(parents=True, exist_ok=True)
    (vault / "prod/best.pt").write_bytes((world / "root/run/best.pt").read_bytes())
    (vault / "MANIFEST.sha256").write_text(f"{h}  ./prod/best.pt\n")
    _pin(world, h)
    return vault, h


def test_vaulted_pin_is_exempt(world):
    vault, h = _vaulted(world)
    rc, out = run(world, "--dry-run", world / "root/run")
    assert rc == 0 and "WOULD DELETE" in out
    assert f"EXEMPT pin {h[:12]} vaulted at {vault / 'prod/best.pt'}" in out


def test_vault_override_is_honoured(world):
    vault, h = _vaulted(world, vault=world / "elsewhere/vault")
    rc, out = run(world, "--dry-run", world / "root/run", extra={"SAFE_RM_VAULT": str(vault)})
    assert rc == 0 and f"vaulted at {vault / 'prod/best.pt'}" in out


def test_no_vault_keeps_the_pin(world):
    h = big_file(world / "root/run/best.pt")
    _pin(world, h)
    rc, out = run(world, "--dry-run", world / "root/run")
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_listed_but_missing_vault_copy_refuses(world):
    vault, _ = _vaulted(world)
    (vault / "prod/best.pt").unlink()
    rc, out = run(world, "--dry-run", world / "root/run")
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_corrupt_vault_copy_refuses(world):
    vault, _ = _vaulted(world)
    (vault / "prod/best.pt").write_bytes(os.urandom(2_000_000))
    rc, out = run(world, "--dry-run", world / "root/run")
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_symlinked_vault_file_refuses(world):
    vault, _ = _vaulted(world)
    real = world / "outside/best.pt"
    real.parent.mkdir()
    (vault / "prod/best.pt").rename(real)
    (vault / "prod/best.pt").symlink_to(real)
    rc, out = run(world, "--dry-run", world / "root/run")
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_vault_entry_that_is_not_a_regular_file_refuses(world):
    # opening a FIFO for hashing would block; only regular files are read
    vault, _ = _vaulted(world)
    (vault / "prod/best.pt").unlink()
    os.mkfifo(vault / "prod/best.pt")
    rc, out = run(world, "--dry-run", world / "root/run", timeout=60)
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_symlinked_vault_directory_refuses(world):
    vault, _ = _vaulted(world)
    (vault / "prod").rename(world / "outside-prod")
    (vault / "prod").symlink_to(world / "outside-prod")
    rc, out = run(world, "--dry-run", world / "root/run")
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_vault_copy_inside_the_target_refuses(world):
    # a manifest entry that climbs out of the vault names the target's own file
    vault, h = _vaulted(world)
    (vault / "prod/best.pt").unlink()
    (vault / "MANIFEST.sha256").write_text(f"{h}  ./../../root/run/best.pt\n")
    rc, out = run(world, "--dry-run", world / "root/run")
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_vault_copy_linked_into_the_target_refuses(world):
    vault, _ = _vaulted(world)
    (vault / "prod/best.pt").unlink()
    (vault / "prod/best.pt").symlink_to(world / "root/run/best.pt")
    rc, out = run(world, "--dry-run", world / "root/run")
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_vault_inside_the_target_refuses(world):
    vault, _ = _vaulted(world, vault=world / "root/run/vault")
    rc, out = run(world, "--dry-run", world / "root/run", extra={"SAFE_RM_VAULT": str(vault)})
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_target_inside_the_vault_refuses(world):
    vault, h = _vaulted(world)
    (vault / "old").mkdir()
    (vault / "old/best.pt").write_bytes((world / "root/run/best.pt").read_bytes())
    rc, out = run(world, "--dry-run", vault / "old")
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_vault_does_not_lift_a_path_pin(world):
    vault, h = _vaulted(world)
    (world / "archive/pk/commands.json").write_text(f'{{"init_sha256": "{h}", "init": "{world}/root/run/best.pt"}}\n')
    rc, out = run(world, "--dry-run", world / "root/run")
    assert rc == 1 and "names" in out and "vaulted at" in out


@pytest.mark.parametrize("name", ["missing/../prod/best.pt", "prod/../prod/best.pt", "*prod/best.pt",
                                  "./prod/./best.pt", "prod//best.pt"])
def test_manifest_name_that_is_not_a_plain_literal_path_refuses(world, name):
    # the digest and the copy at prod/best.pt are right; the name is taken as written (a second '*' is part of it)
    # and any '..', '.' or empty component refuses, even where the filesystem would resolve it
    vault, h = _vaulted(world)
    (vault / "MANIFEST.sha256").write_text(f"{h}  {name}\n")
    rc, out = run(world, "--dry-run", world / "root/run")
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_escaped_manifest_record_refuses(world):
    vault, h = _vaulted(world)
    (vault / "MANIFEST.sha256").write_text(f"\\{h}  ./prod/best.pt\n")
    rc, out = run(world, "--dry-run", world / "root/run")
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


def test_one_unsupported_manifest_line_disables_the_vault(world):
    vault, h = _vaulted(world)
    (vault / "MANIFEST.sha256").write_text(f"{h}  ./prod/best.pt\n{h} ./prod/best.pt\n")
    rc, out = run(world, "--dry-run", world / "root/run")
    assert rc == 1 and "pinned" in out and "EXEMPT" not in out


@pytest.mark.parametrize("record", ["{h} *./prod/best.pt", "{h} *prod/best.pt", "{h}  prod/best.pt"])
def test_valid_text_and_binary_mode_records_are_exempt(world, record):
    vault, h = _vaulted(world)
    (vault / "MANIFEST.sha256").write_text(record.format(h=h) + "\n")
    rc, out = run(world, "--dry-run", world / "root/run")
    assert rc == 0 and f"EXEMPT pin {h[:12]} vaulted at {vault / 'prod/best.pt'}" in out
