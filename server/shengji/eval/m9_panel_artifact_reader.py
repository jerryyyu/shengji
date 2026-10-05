"""Read authenticated panel files into the existing scientific reader.

The caller must authenticate this code and the file-pin mapping, bind it to
the sealed run/packet, and acquire exclusive one-pass read ownership BEFORE
calling. This adapter does not create seals, qualify runtime/source, launch
work, or grant read authority. It never reconstructs or retries collection.
"""
from __future__ import annotations

import copy
import hashlib

from . import observation_queue as guards
from .m9_panel_plan import build_m9_panel_plan
from .m9_panel_readout import read_completed_m9_panels, validate_panel_completion


MAX_FILE_BYTES = 16 * 1024 * 1024
_RECORDS = tuple(f"validated-{index:03d}.json" for index in range(15))
_META = ("owner", "process", "collection", "saved_readout", "plan")


def read_m9_panel_files(files, *, packet_sha256):
    """Hash each input once and parse its same stable byte snapshot.

    ``files`` is an externally authenticated exact mapping from logical names
    to {path, sha256}. All completion metadata is validated before panel files
    are opened; all 15 panel buffers are authenticated before any is parsed.
    No result is returned after a missing, changed, malformed or failed input.
    Memory is bounded by 15 record buffers plus parsed objects, with a 16 MiB
    cap per file. Cooperative stable reads are not an adversarial filesystem
    race defense. Runtime and scientific provenance remain caller obligations.
    """
    guards._strict_sha(packet_sha256, "packet SHA")
    spec = copy.deepcopy(files)
    if type(spec) is not dict or set(spec) != set(_META + _RECORDS):
        raise ValueError("exact five metadata and fifteen panel pins required")
    paths = {}
    for name, entry in spec.items():
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise ValueError("exact path/SHA input pin required")
        guards._strict_sha(entry["sha256"], name)
        paths[name] = guards._canonical_absolute(entry["path"], name)
    if len(set(paths.values())) != len(paths):
        raise ValueError("distinct input paths required")

    hashes = {}

    def authenticate(name):
        raw, _ = guards._stable_read(paths[name], MAX_FILE_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != spec[name]["sha256"]:
            raise ValueError(f"panel input SHA mismatch: {name}")
        hashes[name] = digest
        return raw

    def parse(raw):
        return guards._parse_finite_object(raw.decode("utf-8"))

    # Authenticate all metadata before interpreting any of it.
    metadata = {name: authenticate(name) for name in _META}
    owner, process, collection = (parse(metadata[name])
                                  for name in ("owner", "process", "collection"))
    validate_panel_completion(owner, process, collection, packet_sha256=packet_sha256)
    saved = parse(metadata["saved_readout"])
    if (set(saved) != {"analysis", "provenance"}
            or type(saved["analysis"]) is not dict
            or type(saved["provenance"]) is not dict):
        raise ValueError("saved readout analysis/provenance required")
    analysis = saved["analysis"]
    plan = parse(metadata["plan"])
    expected = {
        "schema": "m9-panel-attempt-v1", "jobs": build_m9_panel_plan(analysis),
        "analysis_sha256": hashlib.sha256(guards._canonical(analysis)).hexdigest(),
        "provenance_verified": False,
    }
    # Exact canonical bytes also distinguish bool/int and int/float fields.
    if guards._canonical(plan) != guards._canonical(expected):
        raise ValueError("published plan differs from saved analysis")
    # Release the five raw metadata buffers before the fifteen panel buffers.
    del metadata

    def load_records():
        buffers = [authenticate(name) for name in _RECORDS]
        return [parse(raw) for raw in buffers]

    result = read_completed_m9_panels(
        analysis, owner, process, collection, packet_sha256=packet_sha256,
        load_records=load_records)
    return {"analysis": result, "input_sha256": hashes,
            "packet_sha256": packet_sha256, "provenance_verified": False}


__all__ = ["read_m9_panel_files"]
