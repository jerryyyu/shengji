"""Export the selected full-mix scratch checkpoint for the paired duel."""
import argparse
from pathlib import Path
import subprocess

import rt4m_joint
from sz2_export_arm import PARITY_DATA, PARITY_ROWS, export_selected, selected_checkpoint


def export(root, recipe_path, parity_data, parity_rows):
    checkpoint, digest, _ = rt4m_joint.completed_inputs(root, recipe_path)
    selected, selected_sha, epoch = selected_checkpoint(root / "A/polish", checkpoint, digest, epochs=8)
    return export_selected(selected, selected_sha, epoch, root / "A/export", "RT4-M-A",
                           parity_data, parity_rows, root_heads=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    try:
        return export(args.root.resolve(), rt4m_joint.RECIPE, PARITY_DATA, PARITY_ROWS)
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"export refused: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
