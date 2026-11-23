"""Open a completed Stage B reservation once under its pinned Codex handoff."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

import readout


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _verified(path, expected):
    if not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{64}", expected):
        raise ValueError(f"missing seal for {path}")
    if path.resolve() != path or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"expected canonical regular file: {path}")
    raw = path.read_bytes()
    if _digest(raw) != expected:
        raise ValueError(f"seal mismatch: {path}")
    return raw


def _holds_clear(paths):
    for path in paths:
        if os.path.lexists(path):
            raise ValueError(f"readout HOLD: {path}")


def read_once(handoff_path, handoff_sha256):
    handoff = json.loads(_verified(Path(handoff_path), handoff_sha256))
    reader = Path(__file__).resolve()
    if (handoff["schema"] != "s158b-handoff-v1" or handoff["reader"] != "codex"
            or handoff["reader_path"] != str(reader)):
        raise ValueError("handoff does not name this Codex reader")
    _verified(reader, handoff["reader_sha256"])
    _verified(reader.with_name("readout.py"), handoff["analysis_sha256"])
    if Path(readout.__file__).resolve() != reader.with_name("readout.py"):
        raise ValueError("unexpected loaded analysis module")
    root = Path(handoff["root"])
    if root != root.resolve() or not root.is_dir():
        raise ValueError("noncanonical run root")
    holds = handoff["hold_paths"]
    if not isinstance(holds, list) or not all(isinstance(p, str) and Path(p).is_absolute() for p in holds):
        raise ValueError("invalid HOLD paths")
    holds = [root / "HOLD", root / "READOUT.HOLD", *holds]
    _holds_clear(holds)
    output = root / "codex-readout"
    if os.path.lexists(output):
        if output.resolve() != output or not (output / "receipt.json").is_file():
            raise ValueError("readout already claimed; no completed receipt")
        receipt_path = output / "receipt.json"
        if receipt_path.resolve() != receipt_path:
            raise ValueError("unexpected saved receipt path")
        receipt = json.loads(receipt_path.read_bytes())
        if receipt["handoff_sha256"] != handoff_sha256:
            raise ValueError("saved result belongs to another handoff")
        return json.loads(_verified(output / "result.json", receipt["result_sha256"]))

    terminal = json.loads(_verified(root / "terminal.json", handoff["terminal_sha256"]))
    expected = dict(schema="s158b-terminal-v1", status="LANE DONE", root=str(root),
                    first_seed=readout.FIRST_SEED, deals=readout.DEALS,
                    dispatch_sha256=handoff["dispatch_sha256"], arm_name=handoff["arm_name"])
    if (not re.fullmatch("[0-9a-f]{64}", expected["dispatch_sha256"])
            or any(terminal.get(k) != v for k, v in expected.items())):
        raise ValueError("terminal does not match reservation and dispatch")
    manifest = json.loads(_verified(root / "slot-seals.json", terminal["manifest_sha256"]))
    seeds = range(readout.FIRST_SEED, readout.FIRST_SEED + readout.DEALS)
    names = {str(seed) for seed in seeds}
    slots = root / "slots"
    if (slots.resolve() != slots or not isinstance(manifest, dict) or set(manifest) != names
            or {p.name for p in slots.iterdir()} != names):
        raise ValueError("slot reservation mismatch")
    if not all(isinstance(v, str) and re.fullmatch("[0-9a-f]{64}", v) for v in manifest.values()):
        raise ValueError("invalid slot seal in manifest")
    _holds_clear(holds)
    output.mkdir()
    raw = {}
    for seed in seeds:
        _holds_clear(holds)
        raw[seed] = _verified(slots / str(seed) / "result.json", manifest[str(seed)])
    _holds_clear(holds)
    try:
        decoded = {seed: json.loads(value) for seed, value in raw.items()}
    except (UnicodeDecodeError, json.JSONDecodeError):
        result = dict(verdict="INVALID", reason="unparseable sealed seed result")
    else:
        result = readout.analyze(decoded, arm_name=expected["arm_name"])
    _holds_clear(holds)
    encoded = json.dumps(result, allow_nan=False, sort_keys=True).encode()
    (output / "result.json").write_bytes(encoded)
    receipt_tmp = output / "receipt.tmp"
    receipt_tmp.write_text(json.dumps(dict(handoff_sha256=handoff_sha256, result_sha256=_digest(encoded))))
    receipt_tmp.rename(output / "receipt.json")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path)
    parser.add_argument("handoff_sha256")
    args = parser.parse_args()
    print(json.dumps(read_once(args.handoff, args.handoff_sha256), sort_keys=True))
