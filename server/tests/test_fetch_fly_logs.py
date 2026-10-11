import json
import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fetch_fly_logs.sh"


def _fake_fly(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fly = bin_dir / "fly"
    fly.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "if test \"$1\" = ssh && test \"$2\" = console; then\n"
        "  ls -1 \"$FAKE_FLY_REMOTE\"\n"
        "elif test \"$1\" = ssh && test \"$2\" = sftp "
        "&& test \"$3\" = get; then\n"
        "  cp \"$FAKE_FLY_REMOTE/$(basename \"$4\")\" \"$5\"\n"
        "else\n"
        "  exit 97\n"
        "fi\n")
    fly.chmod(0o755)
    return bin_dir


def _env(repo: Path, remote: Path, bin_dir: Path):
    env = os.environ.copy()
    env["SHENGJI_FETCH_REPO_ROOT"] = str(repo)
    env["FAKE_FLY_REMOTE"] = str(remote)
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    return env


def test_fetch_stages_validates_backs_up_and_hashes(tmp_path):
    repo = tmp_path / "repo"
    (repo / "server" / "shengji").mkdir(parents=True)
    logs = repo / "logs"
    logs.mkdir()
    old_a = '{"t":1,"e":"round_start","round":1}\n'
    (logs / "A.jsonl").write_text(old_a)
    remote = tmp_path / "remote"
    remote.mkdir()
    appended = ('{"t":2,"e":"play","round":1,"bot":true,'
                '"decision":{"schema":"pv-search-decision-v1",'
                '"policy":"recorded-old-policy","seconds":0.2,'
                '"work_complete":true,"refusal_fallback_worlds":0}}\n')
    (remote / "A.jsonl").write_text(old_a + appended)
    (remote / "B.jsonl").write_text('{"t":3,"e":"round_start","round":2}\n')
    bin_dir = _fake_fly(tmp_path)

    result = subprocess.run(
        [str(SCRIPT)], env=_env(repo, remote, bin_dir), text=True,
        capture_output=True, check=True)

    assert "fetched=2 changed=2 unchanged=0" in result.stdout
    assert (logs / "A.jsonl").read_text() == old_a + appended
    assert (logs / "B.jsonl").read_text() == '{"t":3,"e":"round_start","round":2}\n'
    backups = list((logs / "archive").glob("pre-refresh-*/A.jsonl"))
    assert len(backups) == 1
    assert backups[0].read_text() == old_a
    manifests = list((logs / "manifests").glob("fly-*.sha256"))
    assert len(manifests) == 1
    text = manifests[0].read_text()
    assert "A.jsonl" in text and "B.jsonl" in text
    delta_lines = [line for line in result.stdout.splitlines()
                   if line.startswith("production_log_delta ")]
    assert len(delta_lines) == 2
    a_line = next(line for line in delta_lines if "file=A.jsonl" in line)
    assert "status=ok" in a_line
    report = json.loads(a_line.split(" report=", 1)[1])
    assert report["appended_events"] == 1
    assert report["decision_policy_counts"] == {"recorded-old-policy": 1}
    assert report["unknown_policy_plays"] == 0


def test_invalid_later_download_publishes_nothing(tmp_path):
    repo = tmp_path / "repo"
    (repo / "server" / "shengji").mkdir(parents=True)
    logs = repo / "logs"
    logs.mkdir()
    old = '{"version":"old"}\n'
    (logs / "A.jsonl").write_text(old)
    remote = tmp_path / "remote"
    remote.mkdir()
    (remote / "A.jsonl").write_text('{"version":"would-change"}\n')
    (remote / "B.jsonl").write_text('{not-json}\n')
    bin_dir = _fake_fly(tmp_path)

    result = subprocess.run(
        [str(SCRIPT)], env=_env(repo, remote, bin_dir), text=True,
        capture_output=True)

    assert result.returncode != 0
    assert (logs / "A.jsonl").read_text() == old
    assert not (logs / "B.jsonl").exists()
    assert not (logs / "archive").exists()
    assert not (logs / "manifests").exists()


def test_rewritten_log_is_refreshed_but_delta_attribution_refuses(tmp_path):
    repo = tmp_path / "repo"
    (repo / "server" / "shengji").mkdir(parents=True)
    logs = repo / "logs"
    logs.mkdir()
    (logs / "A.jsonl").write_text('{"t":1,"e":"round_start","round":1}\n')
    remote = tmp_path / "remote"
    remote.mkdir()
    replacement = '{"t":2,"e":"round_start","round":2}\n'
    (remote / "A.jsonl").write_text(replacement)
    bin_dir = _fake_fly(tmp_path)

    result = subprocess.run(
        [str(SCRIPT)], env=_env(repo, remote, bin_dir), text=True,
        capture_output=True, check=True)

    assert (logs / "A.jsonl").read_text() == replacement
    assert "file=A.jsonl status=refused" in result.stderr
    backups = list((logs / "archive").glob("pre-refresh-*/A.jsonl"))
    assert len(backups) == 1
    assert backups[0].read_text() == '{"t":1,"e":"round_start","round":1}\n'
