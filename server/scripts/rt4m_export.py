"""Export the selected full-mix scratch checkpoint for the paired duel."""
import argparse
import json
from pathlib import Path
import subprocess

import rt4m_joint
from sz2_duel_exports import verified_pair
from sz2_export_arm import PARITY_DATA, PARITY_ROWS, export_selected, selected_checkpoint


def selection(root, recipe_path, post_root=None):
    checkpoint, digest, _ = rt4m_joint.completed_inputs(root, recipe_path)
    polish = rt4m_joint.post_output_root(root, post_root) / "A/polish"
    if post_root is not None:
        starts = [line for line in (polish / "status.log").read_text().splitlines() if " POLISH START " in line]
        if len(starts) != 1 or f" ckpt={digest} " not in starts[0]:
            raise ValueError("recovered polish belongs to a different joint checkpoint")
    return selected_checkpoint(polish, checkpoint, digest, epochs=8)


def export(root, recipe_path, parity_data, parity_rows, *, post_root=None):
    selected, selected_sha, epoch = selection(root, recipe_path, post_root)
    return export_selected(selected, selected_sha, epoch, selected.parents[1] / "export", "RT4-M-A",
                           parity_data, parity_rows, root_heads=True)


def duel_words(root, recipe_path, parity_rows, *, post_root=None):
    selected, digest, epoch = selection(root, recipe_path, post_root)
    package, package_sha, belief, belief_sha = verified_pair(
        selected.parents[1] / "export", digest, epoch, "RT4-M-A", parity_rows, root_heads=True)
    words = [f"SHENGJI_PV_BELIEF_CKPT={belief}", f"SHENGJI_PV_BELIEF_SHA256={belief_sha}",
             f"SHENGJI_PV_UNIFIED_CKPT={package}", f"SHENGJI_PV_UNIFIED_SHA256={package_sha}"]
    if any("," in word for word in words):
        raise ValueError("export path cannot be represented by the duel adapter")
    return words


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--post-root", type=Path, help="sibling holding recovered polish and export outputs")
    parser.add_argument("--duel-words", action="store_true", help="verify the existing export and emit the challenger settings")
    args = parser.parse_args()
    try:
        if args.duel_words:
            print(json.dumps(duel_words(args.root.resolve(), rt4m_joint.RECIPE, PARITY_ROWS, post_root=args.post_root)))
            return 0
        return export(args.root.resolve(), rt4m_joint.RECIPE, PARITY_DATA, PARITY_ROWS, post_root=args.post_root)
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"export refused: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
