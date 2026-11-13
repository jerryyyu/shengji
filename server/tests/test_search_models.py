"""The README's search-pipeline and models figures match what their generator writes."""

import subprocess
import sys
from pathlib import Path

BUILD = Path(__file__).resolve().parents[2] / "docs" / "visuals" / "build_search_models.py"


def test_search_and_models_figures_are_current():
    result = subprocess.run([sys.executable, str(BUILD), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
