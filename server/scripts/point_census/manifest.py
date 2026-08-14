"""Build or check the frozen ordered input manifest (stdout only)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, "server")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (build_manifest, emit, load_validated_manifest,  # noqa: E402
                    sha256_bytes, canonical)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["build", "check"])
    ap.add_argument("--logs-dir", default="logs")
    ap.add_argument("--manifest",
                    default="server/scripts/point_census/manifest.json")
    ap.add_argument("--expected-manifest-sha256")
    args = ap.parse_args()
    if args.command == "build":
        emit(build_manifest(args.logs_dir))
        return
    if args.expected_manifest_sha256 is None:
        raise SystemExit("REFUSED: --expected-manifest-sha256 is required for check")
    manifest, ordered, manifest_sha = load_validated_manifest(
        args.manifest, args.logs_dir, args.expected_manifest_sha256)
    emit({"status": "VALID", "files": len(ordered),
          "totals": manifest["totals"],
          "manifest_sha256": manifest_sha,
          "manifest_internal_sha256": sha256_bytes(canonical(manifest))})


if __name__ == "__main__":
    main()
