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
    (logs / "A.jsonl").write_text('{"version":"old"}\n')
    remote = tmp_path / "remote"
    remote.mkdir()
    (remote / "A.jsonl").write_text('{"version":"new"}\n')
    (remote / "B.jsonl").write_text('{"version":"new"}\n')
    bin_dir = _fake_fly(tmp_path)

    result = subprocess.run(
        [str(SCRIPT)], env=_env(repo, remote, bin_dir), text=True,
        capture_output=True, check=True)

    assert "fetched=2 changed=2 unchanged=0" in result.stdout
    assert (logs / "A.jsonl").read_text() == '{"version":"new"}\n'
    assert (logs / "B.jsonl").read_text() == '{"version":"new"}\n'
    backups = list((logs / "archive").glob("pre-refresh-*/A.jsonl"))
    assert len(backups) == 1
    assert backups[0].read_text() == '{"version":"old"}\n'
    manifests = list((logs / "manifests").glob("fly-*.sha256"))
    assert len(manifests) == 1
    text = manifests[0].read_text()
    assert "A.jsonl" in text and "B.jsonl" in text


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
