"""The rehearsal must execute the same modules its launcher verifies."""
from pathlib import Path
import subprocess


def test_import_paths_are_the_verified_paths(tmp_path):
    script = Path(__file__).with_name("rehearse_cloud.sh").read_text()
    guards = "\n".join(line for line in script.splitlines()
                       if "rehearsal import differs" in line)
    assert len(guards.splitlines()) == 2
    for name in ("exploit_duel_s61.py", "hypotheses.py", "different.py"):
        (tmp_path / name).touch()
    prefix = f'''HERE='{tmp_path}'
DUEL="$HERE/exploit_duel_s61.py"
HYP="$HERE/hypotheses.py"
die () {{ echo "$*"; exit 3; }}
'''
    assert subprocess.run(["bash", "-c", prefix + guards]).returncode == 0
    for variable in ("DUEL", "HYP"):
        run = subprocess.run(["bash", "-c", prefix +
                              f'{variable}="$HERE/different.py"\n' + guards],
                             capture_output=True, text=True)
        assert run.returncode == 3
        assert "rehearsal import differs" in run.stdout
