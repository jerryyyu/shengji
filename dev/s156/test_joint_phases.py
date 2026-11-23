from pathlib import Path
import subprocess
import sys

import pytest


PACKET = Path(__file__).resolve().parent
LIB = PACKET.parents[1] / "server/scripts/lanes/lane_lib.sh"
WORKER = """
from pathlib import Path
import hashlib, sys
root, phase = Path(sys.argv[1]), sys.argv[3]
assert sys.argv[2] == "--phase"
assert sys.argv[4:] == ["--provider-sha256", hashlib.sha256((root / "provider.toml").read_bytes()).hexdigest()]
mode = (root / "mode").read_text()
train = root / ("S" if phase == "small" else "M") / "train"
train.mkdir(parents=True, exist_ok=True)
log = train / "status.log"
with (root / "calls").open("a") as f:
    print(phase, file=f)
if phase == "small" and (not log.exists() or mode == "stalled"):
    (train / "checkpoint.pt").write_bytes(b"checkpoint")
    log.write_text("t STOPPED at epoch 1 buffer 25/1000 (STOP file or --max-seconds); checkpoint saved")
    if mode == "provider-drift":
        (root / "provider.toml").write_text("changed config")
    if mode == "stop":
        (train / "STOP").touch()
    sys.exit(3)
if phase == "medium-prefix":
    if mode == "restoration":
        sys.exit(9)
    (train / "checkpoint.pt").write_bytes(b"checkpoint")
    if mode != "missing-report":
        (train / "epoch-1-buffer-400.json").write_text("{}")
    log.write_text("t UTR PAUSED at epoch 1 buffer 400/1000 (report boundary); checkpoint saved")
    sys.exit(7)
if phase == "medium-finish" and mode == "reject":
    sys.exit(8)
best = train / "best.pt"
best.write_bytes(b"best")
digest = hashlib.sha256(best.read_bytes()).hexdigest()
log.write_text(f"t UTR DONE best={best} sha256={digest}")
if mode == "wrong-best":
    best.write_bytes(b"changed")
"""


@pytest.mark.parametrize("mode,rc,terminal,calls", [
    ("pass", 0, "joint arms complete", 4),
    ("reject", 0, "FAIL-OFFLINE at buffer 400", 4),
    ("stop", 1, "operator STOP", 1),
    ("provider-drift", 6, "phase admission failed", 1),
    ("stalled", 6, "no forward checkpoint", 2),
    ("missing-report", 6, "missing matched-prefix witness", 3),
    ("restoration", 9, "provider restoration unverified", 3),
    ("wrong-best", 6, "best checkpoint differs", 2),
])
def test_admitted_phase_sequence(tmp_path, mode, rc, terminal, calls):
    (tmp_path / "worker.py").write_text(WORKER)
    (tmp_path / "mode").write_text(mode)
    (tmp_path / "provider.toml").write_text("fixture config")
    # Exercise the production phase sequence and lane process-group supervision with a fixture trainer.
    harness = """
set -u
root=$1; worker=$root/worker.py; LANE_PY=$2
. "$3"
. "$4"
LANE_NAME=fixture; LANE_HOSTNAME=$(hostname); LANE_LOCK=$root/lock
LANE_RELEASE=$root/RELEASE; LANE_FILES=("$4" "$worker"); LANE_HOLDS=$root/HOLD
provider_sha=$(lane_sha "$root/provider.toml") || exit 6
LANE_FILES+=("$root/provider.toml")
LANE_PINS="$provider_sha  $root/provider.toml"
LANE_STATUS=$root/status; LANE_LOG=$root/log; LANE_MON_POLL=0.05
clean_tree() { return 0; }
lane_identity "${LANE_FILES[@]}" > "$LANE_RELEASE" || exit 6
lane_arm && lane_init && lane_lock_acquire || exit 6
"""
    result = subprocess.run(["bash", "-c", harness + "joint_training", "fixture", str(tmp_path),
                             sys.executable, str(LIB), str(PACKET / "joint_phases.sh")],
                            capture_output=True, text=True, timeout=20)
    status = (tmp_path / "status").read_text()
    assert result.returncode == rc, (result.stderr, status)
    assert terminal in status
    assert (tmp_path / "calls").read_text().splitlines() == ["small", "small", "medium-prefix", "medium-finish"][:calls]
    assert not (tmp_path / "lock").exists()
