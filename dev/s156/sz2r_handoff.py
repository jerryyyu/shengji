"""Publish the sealed SZ2-R reservation without opening duel payloads."""

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from sz2r_producer import run_inputs
from sz2r_read_once import HERE as READER
from sz2r_read_once import PAYLOADS, SOURCES, TS, regular, verified


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _seal_metadata(recipe, recipe_sha, mode, lane):
    seed0, deals, root = run_inputs(recipe, mode, lane)
    name = root.name
    status = regular(lane / f"{name}.status").read_bytes()
    lines = status.decode().splitlines()
    sums = regular(root / "SHA256SUMS").read_bytes()
    sums_sha = digest(sums)
    workers = "1" if mode == "timing" else r"[1-9]\d*"
    forms = (
        rf"START {TS} mode={name} arm=SZ2-R pid=\d+ seed0={seed0} deals={deals} workers={workers} recipe={recipe_sha}",
        rf"LOCKED {TS} after \d+s.*",
        rf"NAMES {TS} ok",
        rf"PRODUCER {TS} .*",
        rf"DONE {TS} recipe={recipe_sha} rows={2 * deals} sums={sums_sha} rc=0",
        rf"UNLOCKED {TS}.*",
    )
    if len(lines) != len(forms) or not all(
        re.fullmatch(f"UTD {form}", line) for form, line in zip(forms, lines)
    ):
        raise ValueError("status does not seal the reserved arm")

    names = set()
    for line in sums.decode().splitlines():
        entry = re.fullmatch(r"[0-9a-f]{64}  \./([^/]+)", line)
        if not entry or entry[1] in names:
            raise ValueError("invalid seal entry")
        names.add(entry[1])
    if names != PAYLOADS or {path.name for path in root.iterdir()} != PAYLOADS | {"SHA256SUMS"}:
        raise ValueError("unexpected sealed file set")
    for name in names:
        regular(root / name)
    return dict(status_sha256=digest(status), sums_sha256=sums_sha)


def terminal_seal(lane, mode, recipe_sha):
    """Verify the status and seal list against the recipe without reading payloads."""
    if mode not in ("pilot", "timing", "screen") or lane.resolve() != lane:
        raise ValueError("wrong mode or reservation")
    recipe = json.loads(verified(lane / "recipe.json", recipe_sha))
    return _seal_metadata(recipe, recipe_sha, mode, lane)


def check_holds(lane, hold_paths):
    if not isinstance(hold_paths, list) or not all(isinstance(path, str) for path in hold_paths):
        raise ValueError("expected a list of HOLD paths")
    for hold in (lane / "HOLD", lane / "READOUT.HOLD", *map(Path, hold_paths)):
        if not hold.is_absolute() or os.path.lexists(hold):
            raise ValueError(f"invalid or active readout HOLD {hold}")


def binding(lane, mode, recipe, recipe_sha, sources, hold_paths):
    check_holds(lane, hold_paths)
    return dict(
        mode=mode,
        reader="codex",
        reader_path=str(READER),
        lane=str(lane),
        sources=sources,
        hold_paths=hold_paths,
        recipe_sha256=recipe_sha,
        **_seal_metadata(recipe, recipe_sha, mode, lane),
    )


def write_handoff(lane: Path, mode: str, recipe_sha: str,
                  sources: dict, hold_paths: list[str]) -> tuple[Path, str]:
    if mode not in ("pilot", "screen") or lane.resolve() != lane or set(sources) != set(SOURCES):
        raise ValueError("wrong mode, sources or reservation")
    for name in SOURCES:
        verified(READER.with_name(name), sources[name])

    recipe = json.loads(verified(lane / "recipe.json", recipe_sha))
    handoff = binding(lane, mode, recipe, recipe_sha, sources, hold_paths)
    if mode == "screen":
        pilot_bytes = regular(lane / "pilot.handoff.json").read_bytes()
        pilot = json.loads(pilot_bytes)
        expected = binding(lane, "pilot", recipe, recipe_sha, sources, pilot["hold_paths"])
        if pilot != expected:
            raise ValueError("screen and pilot reservations differ")
        pilot_sha = digest(pilot_bytes)
        claim = lane / "pilot.read"
        receipt = json.loads(regular(claim / "receipt.json").read_bytes())
        if receipt["handoff_sha256"] != pilot_sha:
            raise ValueError("saved read belongs to another handoff")
        result_sha = receipt["result_sha256"]
        pilot_result = json.loads(verified(claim / "result.json", result_sha))
        if pilot_result["mode"] != "pilot" or pilot_result["validity"] != "VALID":
            raise ValueError("screen requires a valid saved pilot")
        handoff.update(pilot_handoff_sha256=pilot_sha, pilot_result_sha256=result_sha)

    path = lane / f"{mode}.handoff.json"
    data = json.dumps(handoff, allow_nan=False, sort_keys=True).encode()
    with tempfile.NamedTemporaryFile(dir=lane, prefix=f".{mode}.handoff.") as temp:
        temp.write(data)
        temp.flush()
        check_holds(lane, hold_paths)
        try:
            os.link(temp.name, path)
        except FileExistsError:
            if regular(path).read_bytes() != data:
                raise ValueError(f"existing handoff differs: {path}") from None
    return path, digest(data)
