"""The README's decision diagram matches what its generator writes."""

import subprocess
import sys
from pathlib import Path

BUILD = Path(__file__).resolve().parents[2] / "docs" / "visuals" / "build_decision_diagram.py"


def test_decision_diagram_is_current():
    result = subprocess.run([sys.executable, str(BUILD), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
