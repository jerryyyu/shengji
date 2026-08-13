"""Build or check the frozen ordered input manifest (stdout only)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, "server")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import build_manifest, emit, load_validated_manifest  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["build", "check"])
    ap.add_argument("--logs-dir", default="logs")
    ap.add_argument("--manifest",
                    default="server/scripts/point_census/manifest.json")
    args = ap.parse_args()
    if args.command == "build":
        emit(build_manifest(args.logs_dir))
        return
    manifest, ordered = load_validated_manifest(args.manifest, args.logs_dir)
    emit({"status": "VALID", "files": len(ordered),
          "totals": manifest["totals"]})


if __name__ == "__main__":
    main()
