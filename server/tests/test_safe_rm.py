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


def mirror_readable_proc(w):
    """Linux: a non-root caller cannot read other users' or non-dumpable /proc/<pid>/cwd|exe, and safe_rm
    refuses on any unreadable one. Tests scan a mirror of the readable entries (their own processes)."""
    proc = w / f"proc-{time.monotonic_ns()}"
    proc.mkdir()
    for pd in Path("/proc").glob("[0-9]*"):
        links = {}
        for k in ("cwd", "exe"):
            try:
                links[k] = os.readlink(pd / k)
            except OSError:
                links = None
                break
        if links:
            (proc / pd.name).mkdir()
            for k, target in links.items():
                (proc / pd.name / k).symlink_to(target)
    return str(proc)


def run(w, *args, home=None):
    env = dict(os.environ)
    if Path("/proc").is_dir():
        env["SAFE_RM_PROC_ROOT"] = mirror_readable_proc(w)
    env.update(
        HOME=str(home or w / "home"),
        SAFE_RM_ROOTS=str(w / "root"),
        SAFE_RM_LAUNCHERS=str(w / "fleet/*.sh"),
        SAFE_RM_PINS=f"{w}/archive/*/commands.json {w}/archive/*/SHA256SUMS",
        SAFE_RM_KEEP=str(w / "home/.safe_rm.keep"),
    )
    p = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], env=env,
                       capture_output=True, text=True, timeout=300)
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
        rc, out = run(world, world / "busy")
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


def test_missing_proc_root_override_refuses(world, monkeypatch):
    monkeypatch.setenv("SAFE_RM_PROC_ROOT", str(world / "no-such-proc"))
    env_run = dict(os.environ)
    target = world / "root/old-run"
    p = subprocess.run([sys.executable, str(SCRIPT), "--dry-run", str(target)], capture_output=True, text=True,
                       env={**env_run, "HOME": str(world / "home"), "SAFE_RM_ROOTS": str(world / "root"),
                            "SAFE_RM_LAUNCHERS": str(world / "fleet/*.sh"),
                            "SAFE_RM_KEEP": str(world / "home/.safe_rm.keep")}, timeout=300)
    assert p.returncode == 1 and "SAFE_RM_PROC_ROOT" in p.stdout and target.is_dir()


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
    if Path("/proc").is_dir():
        env["SAFE_RM_PROC_ROOT"] = mirror_readable_proc(world)
    out = subprocess.run(
        ["/bin/bash", "-c", f'"{sys.executable}" "{SCRIPT}" --dry-run "{target}"; echo "rc=$?"'],
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


@pytest.mark.parametrize("failure", [PermissionError, FileNotFoundError])
def test_procfs_inventory_distinguishes_unreadable_from_exited(monkeypatch, failure):
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
    if failure is PermissionError:
        assert len(reasons) == 2
        assert all("inventory unavailable" in reason for reason in reasons)
    else:
        assert reasons == []
