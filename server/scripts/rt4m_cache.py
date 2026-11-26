"""Build one RT4-M scratch cache partition from its completed joint checkpoint."""
import argparse
from pathlib import Path
import plistlib
import shutil
import subprocess
from uuid import UUID
import sys

import rt4m_joint
from shengji.train.unified_readout import CACHE_DEFAULT_ENCODE_ROUNDS
from sz2_cache_arm import MEDIUM_ENCODE_ROUNDS, WORKERS, write_partition
from sz2_polish_arm import polish_checkpoint

RT4_SAMPLE = dict(cap_rows=50_000_000, seed=1, chunks=43_454, rows=49_999_996,
                  of_chunks=59_533, of_rows=68_534_944)


def inputs(root, output, recipe_path, encode_rounds=CACHE_DEFAULT_ENCODE_ROUNDS):
    if encode_rounds not in (CACHE_DEFAULT_ENCODE_ROUNDS, MEDIUM_ENCODE_ROUNDS):
        raise ValueError("unsupported RT4-M cache encode size")
    checkpoint, digest, recipe = rt4m_joint.completed_inputs(root, recipe_path)
    identity = f"{digest}-{rt4m_joint.RECIPE_SHA256}"
    if encode_rounds != CACHE_DEFAULT_ENCODE_ROUNDS:
        identity += f"-encode{encode_rounds}"
    cache = output / "A" / identity
    if not cache.resolve().is_relative_to(output.resolve()):
        raise ValueError("derived cache directory escapes the cache root")
    return checkpoint, cache, recipe


def partition(root, output, worker, recipe_path, *, encode_rounds=CACHE_DEFAULT_ENCODE_ROUNDS):
    checkpoint, cache, recipe = inputs(root, output, recipe_path, encode_rounds)
    return write_partition(checkpoint, cache, recipe, worker, encode_rounds=encode_rounds,
                           sample_rows=RT4_SAMPLE["cap_rows"])


def polish(root, output, recipe_path, *, encode_rounds=CACHE_DEFAULT_ENCODE_ROUNDS, finish_selection=False):
    checkpoint, cache, recipe = inputs(root, output, recipe_path, encode_rounds)
    return polish_checkpoint(checkpoint, cache, recipe, root / "A/polish", epochs=8, lr=1e-3,
                             expected_sample=RT4_SAMPLE, expected_encode_rounds=encode_rounds,
                             finish_selection=finish_selection)


def check_cache_storage(root, cache_root, volume_uuid, cache_gib, internal_gib):
    """Admit a split-volume stage against the mounted cache volume and both stage-specific floors."""
    under_volumes = cache_root.absolute().is_relative_to("/Volumes")
    cache_root = cache_root.resolve()
    if (volume_uuid, cache_gib, internal_gib) == (None, None, None) and not (
            under_volumes or cache_root.is_relative_to("/Volumes")):
        return
    if volume_uuid is None or not cache_gib or not internal_gib or min(cache_gib, internal_gib) < 1:
        raise ValueError("split-volume admission requires a volume UUID and two positive free-space floors")
    uuid = str(UUID(volume_uuid)).upper()
    probe = subprocess.run(["/usr/sbin/diskutil", "info", "-plist", uuid], capture_output=True)
    if probe.returncode:
        raise ValueError("cache volume UUID is unavailable")
    try:
        info = plistlib.loads(probe.stdout)
    except plistlib.InvalidFileException as exc:
        raise ValueError("invalid diskutil volume information") from exc
    if not isinstance(info, dict) or info.get("VolumeUUID") != uuid or not info.get("MountPoint"):
        raise ValueError("cache volume UUID is not mounted")
    mount = Path(info["MountPoint"]).resolve(strict=True)
    if not mount.is_mount() or not cache_root.is_relative_to(mount) or cache_root == mount:
        raise ValueError("cache output must be under the mounted cache volume")
    parent = next(path for path in (cache_root, *cache_root.parents) if path.exists())
    device = mount.stat().st_dev
    if parent.stat().st_dev != device or root.stat().st_dev == device:
        raise ValueError("cache and internal run must use the intended separate volumes")
    for path, floor in ((parent, cache_gib), (root, internal_gib)):
        if shutil.disk_usage(path).free < floor * 2**30:
            raise ValueError(f"{path} has less than the required {floor} GiB free")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--encode-rounds-per-batch", type=int, choices=(CACHE_DEFAULT_ENCODE_ROUNDS, MEDIUM_ENCODE_ROUNDS),
                        default=CACHE_DEFAULT_ENCODE_ROUNDS)
    parser.add_argument("--cache-volume-uuid", help="expected mounted macOS volume for a split-volume stage")
    parser.add_argument("--min-cache-free-gib", type=int)
    parser.add_argument("--min-internal-free-gib", type=int)
    stage = parser.add_mutually_exclusive_group(required=True)
    stage.add_argument("--worker", type=int, choices=range(WORKERS))
    stage.add_argument("--polish", action="store_true")
    stage.add_argument("--finish-selection", action="store_true",
                       help="publish the missing winner link from a completed polish")
    args = parser.parse_args()
    try:
        root, cache_root = args.root.resolve(), args.cache_root.resolve()
        check_cache_storage(root, args.cache_root, args.cache_volume_uuid, args.min_cache_free_gib,
                            args.min_internal_free_gib)
        if args.polish or args.finish_selection:
            return polish(root, cache_root, rt4m_joint.RECIPE,
                          encode_rounds=args.encode_rounds_per_batch, finish_selection=args.finish_selection)
        return partition(root, cache_root, args.worker, rt4m_joint.RECIPE,
                         encode_rounds=args.encode_rounds_per_batch)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"invalid RT4-M cache: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
