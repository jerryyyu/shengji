"""Synthetic launcher recovery witnesses using a stub workload and guards."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

LAUNCHER = Path(__file__).with_name("claude_s61dev_cloud.final.sh").resolve()


def _write(path: Path, text: str, executable: bool = False) -> None:
    path.write_text(text)
    if executable:
        path.chmod(0o755)


def _driver(tmp: Path, *, recovery: int, attempt: str = ""):
    tmp.mkdir(parents=True, exist_ok=True)
    root, out, fakebin = tmp / "root", tmp / "out", tmp / "bin"
    root.mkdir(exist_ok=True)
    fakebin.mkdir(exist_ok=True)
    tree = tmp / "tree"
    tree.mkdir(exist_ok=True)
    (tree / "server").mkdir(exist_ok=True)
    _write(tree / "fly.toml", "[env]\nSHENGJI_BOT='stub'\n")
    _write(fakebin / "nproc", "#!/bin/sh\necho 64\n", True)
    _write(fakebin / "df", "#!/bin/sh\necho 'Filesystem 1G-blocks Used Available Capacity Mounted on'\necho '/dev/stub 10G 1G 9G 10% /'\n", True)
    _write(fakebin / "setsid", "#!/bin/sh\nexec \"$@\"\n", True)
    _write(fakebin / "timeout", "#!/bin/sh\nshift 2\nexec \"$@\"\n", True)
    _write(fakebin / "time", "#!/bin/sh\nout=\nwhile [ $# -gt 0 ]; do case \"$1\" in -v) shift;; -o) out=$2; shift 2;; *) break;; esac; done\n\"$@\"; rc=$?\n[ -z \"$out\" ] || printf '%s\\n' 'Maximum resident set size (kbytes): 1' > \"$out\"\nexit $rc\n", True)
    _write(fakebin / "ps", "#!/bin/sh\ncase \"$*\" in *pgid=*p*) printf '%s\\n' \"$4\";; *) exit 0;; esac\n", True)
    fake_py = tmp / "fake-python"
    _write(fake_py, "#!/bin/sh\n" + "\n".join([
        "out=",
        "while [ $# -gt 0 ]; do",
        "  [ \"$1\" = --out ] && { out=$2; shift 2; continue; }",
        "  shift",
        "done",
        "[ -n \"$out\" ] || exit 2",
        "binding=\"$out.resume.json\"",
        "[ -e \"$binding\" ] || printf '%s\\n' '{\"schema\":\"s61dev-resume-v1\"}' > \"$binding\"",
        "rows=${FAKE_ROWS:-1}",
        "i=0",
        "while [ $i -lt $rows ]; do",
        "  printf '%s\\n' \"{\\\"arm\\\":\\\"identity\\\",\\\"seed\\\":$((218060910 + i)),\\\"mirror\\\":$i,\\\"round_kind\\\":\\\"first\\\",\\\"trump_rank\\\":\\\"2\\\",\\\"planned_banker\\\":null}\" >> \"$out\"",
        "  i=$((i + 1))",
        "done",
        "exit ${FAKE_RC:-0}",
        "",
    ]), True)
    env = os.environ.copy()
    env.update({"PATH": f"{fakebin}:{env['PATH']}", "LANE_ROOT": str(root), "OUT": str(out), "R": str(tree),
                "PY": str(fake_py), "TIME_BIN": str(fakebin / "time"), "LANE_FUNCTIONS_ONLY": "1", "RECOVERY": str(recovery), "ATTEMPT_ID": attempt, "LANE_SLEEP": "0",
                "WAIT_CEILING": "30", "DEALS": "2", "WORKERS": "1", "KILL_AFTER": "10", "BACKSTOP": "10",
                "FAKE_RC": "1" if not recovery else "0", "FAKE_ROWS": "1" if not recovery else "3"})
    script = f"\n".join([
        "set -u",
        f"source {LAUNCHER} || exit $?",
        "DEALS=2; WORKERS=1; KILL_AFTER=10; BACKSTOP=10",
        "placeholder_guard() { :; }; verify_tree() { :; }; check_packages() { :; }",
        "check_toml() { :; }; check_compiled() { :; }; check_names() { echo names-ok; }",
        "mem_guard() { :; }; wait_legacy_peers() { :; }; predispatch_guard() { :; }; run_group_live() { :; }",
        'FLY_SHA=$(sha256sum "$R/fly.toml" | cut -d" " -f1)',
        "write_recipe() { printf '%s\\n' '{\"stub\":true}' > \"$OUT/recipe.json\"; }",
        'RELEASE="$LANE_ROOT/claude_${LANE}${ATTEMPT_TAG}.RELEASE"',
        'printf "%s\\n" "$SELF_SHA" > "$RELEASE"',
        "run_lane",
        "",
    ])
    return ["bash", "-c", script], env


def _run(tmp: Path, *, recovery: int, attempt: str = "") -> subprocess.CompletedProcess[str]:
    cmd, env = _driver(tmp, recovery=recovery, attempt=attempt)
    return subprocess.run(cmd, env=env, text=True, capture_output=True)


def test_interrupted_attempt_recovers_without_clobbering_prior_files(tmp_path):
    first = _run(tmp_path, recovery=0)
    assert first.returncode != 0
    root, out = tmp_path / "root", tmp_path / "out"
    status = (root / "claude_s61dev_screen.status").read_text()
    assert status.count("DEV start:") == 1
    assert status.count("DEV END rc=1") == 1
    assert not any("output sealed; rc/status only" in line for line in status.splitlines())
    assert (out / "SHA256SUMS").exists()
    old_files = {name: (out / name).read_bytes() for name in ("duel.stdout", "duel.stderr", "duel.time", "duel.jsonl", "SHA256SUMS")}
    second = _run(tmp_path, recovery=1, attempt="2")
    assert second.returncode == 0, second.stderr + second.stdout
    text = (root / "claude_s61dev_screen.status.attempt-2").read_text()
    assert text.count("DEV start:") == 1
    assert text.count("DEV END rc=0") == 1
    assert text.count("LANE DONE") == 1
    assert (out / "SHA256SUMS.attempt-2").exists()
    assert (out / "SHA256SUMS").read_bytes() == old_files["SHA256SUMS"]
    for name in ("duel.stdout", "duel.stderr", "duel.time"):
        assert (out / name).read_bytes() == old_files[name]
    assert (out / "duel.jsonl").read_bytes() != old_files["duel.jsonl"]
    for suffix in ("stdout", "stderr", "time"):
        assert (out / f"duel.attempt-2.{suffix}").exists()


def test_fresh_and_completed_or_unsafe_recovery_refuse(tmp_path):
    assert _run(tmp_path, recovery=0).returncode != 0
    fresh = _run(tmp_path, recovery=0)
    assert fresh.returncode != 0
    assert "output root" in fresh.stdout
    recovered = _run(tmp_path, recovery=1, attempt="2")
    assert recovered.returncode == 0, recovered.stderr + recovered.stdout
    attempt_two = tmp_path / "root/claude_s61dev_screen.status.attempt-2"
    attempt_two.write_text("\n".join(line for line in attempt_two.read_text().splitlines()
                                      if "output sealed; rc/status only" not in line) + "\n")
    completed = _run(tmp_path, recovery=1, attempt="3")
    assert completed.returncode == 0, completed.stderr + completed.stdout
    completed_refusal = _run(tmp_path, recovery=1, attempt="4")
    assert completed_refusal.returncode != 0
    assert "completed lane" in completed_refusal.stdout
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    (unsafe / "duel.jsonl").write_bytes(b'{"partial":true}')
    cmd, env = _driver(tmp_path / "unsafe-driver", recovery=1, attempt="4")
    env["OUT"] = str(unsafe)
    refused = subprocess.run(cmd, env=env, text=True, capture_output=True)
    assert refused.returncode != 0
    assert "config/source binding" in refused.stdout


def test_launcher_pins_repaired_harness_paths():
    text = LAUNCHER.read_text()
    assert "/root/codex-s61dev-repair/exploit_duel_s61.py" in text
    assert "/root/codex-s61dev-repair/hypotheses.py" in text
    import hashlib
    digest = hashlib.sha256(LAUNCHER.with_name("exploit_duel_s61.py").read_bytes()).hexdigest()
    assert f"DUEL_SHA={digest}" in text
