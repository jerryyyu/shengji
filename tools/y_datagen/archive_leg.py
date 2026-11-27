#!/usr/bin/env python3
"""Compress a completed leg and check the restored members against its producer seal."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

from launch import _volume


def sealed_members(store, terminal, expected_sha):
    raw = terminal.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("terminal digest differs")
    result = json.loads(raw)
    if result["status"] != "completed" or result["returncode"] != 0 or result["lock_retained"]:
        raise ValueError("leg is incomplete")
    seal = result["leg_seal"]
    manifest_bytes = (store / "manifest.json").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != seal["manifest_sha256"]:
        raise ValueError("store manifest differs from seal")
    manifest = json.loads(manifest_bytes)
    members = {f"{name}.json": seal[f"{name}_sha256"] for name in ("manifest", "run", "runtime")}
    for i, shard in enumerate(manifest["shards"]):
        stem = f"shards/cluster-{i:06d}"
        if shard["path"] != stem + ".jsonl" or shard["sidecar"] != stem + ".json":
            raise ValueError("unexpected member path")
        members[shard["path"]] = shard["sha256"]
        members[shard["sidecar"]] = shard["sidecar_sha256"]
    return members, seal


def verify(archive, members):
    with subprocess.Popen(["zstd", "-qdc", "--", archive], stdout=subprocess.PIPE) as proc:
        try:
            with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
                seen = set()
                member_bytes = 0
                for entry in tar:
                    if not entry.isfile() or entry.name not in members or entry.name in seen:
                        raise ValueError(f"unexpected archive member: {entry.name}")
                    with tar.extractfile(entry) as restored:
                        digest = hashlib.sha256()
                        while chunk := restored.read(1024 * 1024):
                            digest.update(chunk)
                        if digest.hexdigest() != members[entry.name]:
                            raise ValueError(f"restored member differs: {entry.name}")
                    seen.add(entry.name)
                    member_bytes += entry.size
            if seen != members.keys():
                raise ValueError("incomplete archive")
            while proc.stdout.read(1024 * 1024):
                pass
        finally:
            proc.stdout.close()
        if proc.wait():
            raise ValueError("zstd decompression failed")
    return member_bytes


def archive_leg(store, terminal, expected_sha, destination):
    members, seal = sealed_members(store, terminal, expected_sha)
    destination = destination.parent.resolve(strict=True) / destination.name

    def check_destination():
        if "archive_uuid" in seal:
            mount = _volume(seal["archive_uuid"], internal=False)
            if (not destination.parent.is_relative_to(mount)
                    or destination.parent.stat().st_dev != mount.stat().st_dev):
                raise ValueError("destination is outside the sealed archive volume")

    check_destination()
    if destination.resolve().is_relative_to(store.resolve()):
        raise ValueError("archive must be outside the raw store")
    # Cooperating retries serialize publication on filesystems without hard links.
    with destination.with_name(destination.name + ".lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if destination.is_symlink():
            raise ValueError("linked archive")
        if destination.exists():
            member_bytes = verify(destination, members)
            check_destination()
        else:
            with tempfile.TemporaryDirectory(dir=destination.parent) as scratch:
                staged = Path(scratch) / "leg.tar.zst"
                with staged.open("xb") as output:
                    with subprocess.Popen(["zstd", "-q", "-3", "-T1", "-c"], stdin=subprocess.PIPE,
                                          stdout=output) as proc:
                        with proc.stdin, tarfile.open(fileobj=proc.stdin, mode="w|") as tar:
                            for name in members:
                                path = store / name
                                info = tar.gettarinfo(str(path), arcname=name)
                                if not info.isfile():
                                    raise ValueError(f"expected regular source member: {name}")
                                with path.open("rb") as source:
                                    tar.addfile(info, source)
                        if proc.wait():
                            raise ValueError("zstd compression failed")
                    output.flush()
                    os.fsync(output.fileno())
                member_bytes = verify(staged, members)
                check_destination()
                staged.rename(destination)
        compressed_bytes = destination.stat().st_size
    return {"archive": str(destination), "compressed_bytes": compressed_bytes,
            "raw_member_bytes": member_bytes, "compression_ratio": member_bytes / compressed_bytes,
            "verified_members": len(members), "terminal_sha256": expected_sha}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store", type=Path)
    parser.add_argument("terminal", type=Path)
    parser.add_argument("terminal_sha256")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(archive_leg(args.store, args.terminal, args.terminal_sha256, args.destination)))
