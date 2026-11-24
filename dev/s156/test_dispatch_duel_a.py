"""The Mini dispatcher must present the exact preflight identity to the queued Ultra launcher."""
import hashlib
import os
from pathlib import Path
import subprocess

import pytest


DISPATCH = Path(__file__).with_name("dispatch_duel_a.sh")
ID = "c" * 64


@pytest.mark.parametrize("case", ["admitted", "other-row", "wrong-release", "foreign-script", "bad-preflight"])
def test_mini_dispatch_requires_current_queue_and_matching_source(tmp_path, case):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "fleet_queue.json").write_text("{}\n")
    (tools / "fleet_queue.py").write_text(
        "import os, sys\n"
        "assert sys.argv[1:] == ['next', 'ultra']\n"
        "assert 'FLEET_QUEUE' not in os.environ\n"
        "print(os.environ['QUEUE_ROW'])\n"
    )
    bins = tmp_path / "bin"
    bins.mkdir()
    for name, source in {
        "hostname": "echo Jerrys-Mac-mini.local",
        "ssh": """
printf '%s\\n' "$*" >> "$SSH_TRACE"
case "$*" in
    *shasum*) echo "$REMOTE_SHA  remote" ;;
    *--preflight*) echo "$PREFLIGHT" ;;
    *nohup*) exit 0 ;;
    *) exit 9 ;;
esac
""",
    }.items():
        path = bins / name
        path.write_text("#!/bin/bash\n" + source)
        path.chmod(0o755)
    launcher = tmp_path / DISPATCH.name
    launcher.write_text(DISPATCH.read_text().replace(
        "/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/tools", str(tools)))
    trace = tmp_path / "ssh.trace"
    row = f"sz2-duel-a-v1:released sha={ID[:8]}"
    env = {**os.environ, "PATH": str(bins) + os.pathsep + os.defpath, "SSH_TRACE": str(trace),
           "FLEET_QUEUE": str(tmp_path / "foreign-queue.json"),
           "QUEUE_ROW": {"other-row": "another:released sha=cccccccc",
                         "wrong-release": "sz2-duel-a-v1:released sha=dddddddd"}.get(case, row),
           "REMOTE_SHA": hashlib.sha256(launcher.read_bytes()).hexdigest() if case != "foreign-script" else "f"*64,
           "PREFLIGHT": "invalid" if case == "bad-preflight" else ID}
    result = subprocess.run(["/bin/bash", launcher, "--dispatch"], env=env, capture_output=True, text=True)
    calls = trace.read_text().splitlines()
    launches = [line for line in calls if "nohup" in line]
    if case == "admitted":
        assert result.returncode == 0, result
        assert len(launches) == 1 and ID in launches[0]
    else:
        assert result.returncode != 0 and not launches
