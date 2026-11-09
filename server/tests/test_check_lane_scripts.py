"""check_lane_scripts.py: the glob-to-wc count and the launcher-must-source-lane_lib rule."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("check_lane_scripts", SCRIPTS / "check_lane_scripts.py")
cls = importlib.util.module_from_spec(spec)
sys.modules["check_lane_scripts"] = cls
spec.loader.exec_module(cls)


def rules(tmp_path, text, name="x.sh", strict=False, where=None):
    d = where or tmp_path
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(text)
    return [(r, level) for _, r, level, _ in cls.check_file(p, strict)]


@pytest.mark.parametrize("line", [
    'n=$(ls "$OUT"/shards/*.json | wc -l)',
    "ls $D/cluster-*.json 2>/dev/null | wc -l",
    "N=`ls shards/cluster-?.json | grep -v tmp | wc -l`",
    "ls -1 $D/[a-z]*.json \\\n  | wc -l",
])
def test_glob_wc_is_an_error(tmp_path, line):
    assert ("glob-wc", "ERROR") in rules(tmp_path, f"#!/bin/bash\n{line}\n")


@pytest.mark.parametrize("line", [
    "find \"$D\" -name 'cluster-*.json' | wc -l",
    "ls \"$D\" | wc -l",
    "ls '$D/*.json' | wc -l",
    "grep -c 'x*' f | wc -l",
    "ls *.json; wc -l f",
    "ls *.json || wc -l f",
    "# ls *.json | wc -l",
])
def test_glob_wc_negatives(tmp_path, line):
    assert rules(tmp_path, f"#!/bin/bash\n{line}\n") == []


LAUNCHER = '#!/bin/bash\nRELEASE=$W/RELEASE\npython3 gen.py &\n'


def test_launcher_in_lanes_dir_must_source_the_library(tmp_path, monkeypatch):
    monkeypatch.setattr(cls, "LANES", tmp_path / "lanes")
    assert rules(tmp_path, LAUNCHER, where=tmp_path / "lanes") == [("lane-lib-not-sourced", "ERROR")]
    ok = '#!/bin/bash\n. "$(dirname "$0")/lane_lib.sh"\n' + LAUNCHER
    assert rules(tmp_path, ok, name="y.sh", where=tmp_path / "lanes") == []


def test_launcher_elsewhere_warns_unless_required_or_strict(tmp_path):
    assert rules(tmp_path, LAUNCHER) == [("lane-lib-not-sourced", "WARNING")]
    assert rules(tmp_path, LAUNCHER, strict=True) == [("lane-lib-not-sourced", "ERROR")]
    assert rules(tmp_path, "# lane-lib: required\n" + LAUNCHER, name="r.sh") == [("lane-lib-not-sourced", "ERROR")]


@pytest.mark.parametrize("mark", ["setsid python3 gen.py", "nohup ./gen.sh &", "mkdir /x/.claude-host.lock"])
def test_launcher_marks(tmp_path, mark):
    assert rules(tmp_path, f"#!/bin/bash\n{mark}\n", strict=True) == [("lane-lib-not-sourced", "ERROR")]


def test_not_a_launcher_and_comment_mentions_do_not_count(tmp_path):
    assert rules(tmp_path, "#!/bin/bash\n# reads the RELEASE file of others\necho hi\n", strict=True) == []


def test_exempt_needs_a_reason(tmp_path):
    assert rules(tmp_path, "# lane-lib: exempt read-only status report\n" + LAUNCHER, strict=True) == []
    assert rules(tmp_path, "# lane-lib: exempt\n" + LAUNCHER, name="e.sh") == [("lane-lib-not-sourced", "ERROR")]


def test_main_exit_codes(tmp_path, capsys):
    (tmp_path / "bad.sh").write_text("ls *.json | wc -l\n")
    (tmp_path / "warn.sh").write_text(LAUNCHER)
    assert cls.main([str(tmp_path / "warn.sh")]) == 0
    assert cls.main([str(tmp_path)]) == 1
    assert cls.main(["--strict", str(tmp_path / "warn.sh")]) == 1
    assert cls.main([str(tmp_path / "missing.sh")]) == 2


def test_the_repository_passes():
    assert cls.main([]) == 0
