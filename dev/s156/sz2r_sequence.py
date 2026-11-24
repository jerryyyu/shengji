"""Pilot, capacity check and sealed screen under the launcher's admission callback."""
import json
import math
import os
import re
from pathlib import Path

from sz2r_handoff import check_holds, terminal_seal, write_handoff
from sz2r_producer import run_inputs
from sz2r_read_once import HERE, SOURCES, read_once, verified
from sz2r_run import produce


def timing_estimate(lane, recipe, recipe_sha, workers):
    seal = terminal_seal(lane, "timing", recipe_sha)
    _, deals, root = run_inputs(recipe, "timing", lane)
    sums = verified(root / "SHA256SUMS", seal["sums_sha256"]).decode().splitlines()
    time_sha, = [line.split()[0] for line in sums if line.endswith("  ./duel.time")]
    timing = verified(root / "duel.time", time_sha).decode()
    wall, = re.findall(r"(?m)^\s*([0-9]+(?:\.[0-9]+)?) real\s+", timing)
    rss, = re.findall(r"(?m)^\s*(\d+)\s+maximum resident set size\s*$", timing)
    if not math.isfinite(float(wall)) or float(wall) <= 0 or int(rss) <= 0:
        raise ValueError("invalid one-worker resource measurement")
    return dict(seconds=float(wall), peak_bytes=int(rss),
                projected_seconds=float(wall) * math.ceil(recipe["deals"] / workers) / deals,
                projected_bytes=int(rss) * (workers + 1))


def supervise(lane: Path, *, recipe_sha, sources, hold_paths, workers, max_seconds,
              max_bytes, admit, publish):
    """Return the screen handoff after publication; leave its one-shot read to Codex.

    admit rechecks the supervising launcher's release, host lock and queue guards.
    publish durably records the handoff path and digest or raises.
    """
    def admitted():
        check_holds(lane, hold_paths)
        admit()

    admitted()
    if set(sources) != set(SOURCES):
        raise ValueError("incomplete reader source pins")
    for name in SOURCES:
        verified(HERE.with_name(name), sources[name])
    recipe = json.loads(verified(lane / "recipe.json", recipe_sha))
    if (type(workers) is not int or not 1 <= workers <= 24
            or any(type(v) is not int or v <= 0 for v in (max_seconds, max_bytes))):
        raise ValueError("expected bounded worker count and positive capacity limits")
    def paths(mode):
        _, _, root = run_inputs(recipe, mode, lane)
        return (root, lane / f"{root.name}.status")

    modes = ("pilot", "timing", "screen")
    existing = {}
    for mode in modes:
        flags = [os.path.lexists(p) for p in paths(mode)]
        if any(flags):
            terminal_seal(lane, mode, recipe_sha)
        existing[mode] = all(flags)
    if ((existing["screen"] and not existing["timing"])
            or (existing["timing"] and not existing["pilot"])):
        raise ValueError("completed successor has a missing predecessor")
    for mode in ("pilot", "screen"):
        handoff = lane / f"{mode}.handoff.json"
        claim = lane / f"{mode}.read"
        if os.path.lexists(handoff) and not existing[mode]:
            raise ValueError("handoff has no completed producer")
        if os.path.lexists(claim) and not (handoff.is_file() and (claim / "receipt.json").is_file()):
            raise ValueError("incomplete prior read; reservation retained")
    if existing["timing"] and not (lane / "pilot.read/receipt.json").is_file():
        raise ValueError("timing lacks its prior pilot check")

    for mode in modes:
        admitted()
        if not existing[mode]:
            nworkers = {"pilot": min(20, workers), "timing": 1, "screen": workers}[mode]
            produce(lane, mode, nworkers, recipe_sha, admitted)
        if mode == "timing":
            estimate = timing_estimate(lane, recipe, recipe_sha, workers)
            print(json.dumps(dict(timing=estimate)), flush=True)
            if estimate["projected_seconds"] > max_seconds or estimate["projected_bytes"] > max_bytes:
                raise ValueError("timing projection exceeds reviewed capacity")
            continue
        handoff, digest = write_handoff(lane, mode, recipe_sha, sources, hold_paths)
        admitted()
        publish(handoff, digest)
        if mode == "screen":
            return handoff, digest
        admitted()
        pilot = read_once(handoff, digest)
        if pilot["validity"] != "VALID":
            raise ValueError("pilot invalid; timing and screen withheld")
