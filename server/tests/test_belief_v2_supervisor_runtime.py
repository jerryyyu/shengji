"""Runtime-path witnesses for the one-shot R4 supervisor."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import venv


SCRIPT = (Path(__file__).parents[1] / "scripts" /
          "belief_v2_supervisor.py")
PATH_PROBE = """
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location("belief_v2_supervisor", sys.argv[1])
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(module._absolute_python_path(Path(sys.argv[2])))
"""


def test_supervisor_preserves_venv_python_symlink_for_workers(tmp_path):
    environment = tmp_path / "worker-venv"
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / "bin" / "python"
    if not python.is_symlink():
        python.unlink()
        python.symlink_to(Path(sys.executable).resolve())
    site_packages = next((environment / "lib").glob("python*/site-packages"))
    (site_packages / "belief_worker_probe.py").write_text(
        "VALUE = 'venv-loaded'\n", encoding="ascii")

    probe = subprocess.run(
        [sys.executable, "-P", "-B", "-c", PATH_PROBE,
         str(SCRIPT), str(python)],
        check=True, capture_output=True, text=True)
    selected = Path(probe.stdout.strip())

    assert selected == python
    assert selected.resolve() == Path(sys.executable).resolve()
    completed = subprocess.run(
        [str(selected), "-P", "-B", "-c",
         "import belief_worker_probe; print(belief_worker_probe.VALUE)"],
        check=True, capture_output=True, text=True)
    assert completed.stdout == "venv-loaded\n"
