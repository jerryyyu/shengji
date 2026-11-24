"""Connect the guarded fleet launcher to the SZ2-R producer and readout handoff."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from sz2r_read_once import SOURCES, regular, verified
from sz2r_sequence import supervise


def sha(path):
    with regular(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def publish(path, handoff_sha):
    handoff = json.loads(verified(path, handoff_sha))
    receipt = dict(handoff=str(path), handoff_sha256=handoff_sha,
                   sums_sha256=handoff["sums_sha256"], recipe_sha256=handoff["recipe_sha256"],
                   reader=handoff["reader"], reader_path=handoff["reader_path"],
                   reader_sha256=handoff["sources"]["sz2r_read_once.py"])
    data = (json.dumps(receipt, sort_keys=True) + "\n").encode()
    target = path.with_name(f"{handoff['mode']}.published.json")
    with tempfile.NamedTemporaryFile(dir=path.parent) as temp:
        temp.write(data)
        temp.flush()
        os.fsync(temp.fileno())
        try:
            os.link(temp.name, target)
        except FileExistsError:
            if regular(target).read_bytes() != data:
                raise ValueError(f"published handoff differs at {target}") from None
    print(json.dumps(receipt, sort_keys=True), flush=True)


def run(lane, armed_id, owner):
    if lane != Path(__file__).resolve().parent or not re.fullmatch("[0-9a-f]{64}", armed_id) or owner <= 1:
        raise ValueError("invalid lane reservation, launcher identity or lock owner")

    def admit():
        subprocess.run(["/bin/bash", str(lane / "sz2r_fleet.sh"), "admit", armed_id, str(owner)],
                       check=True)

    admit()
    capacity = json.loads(regular(lane / "sz2r_capacity.json").read_bytes())
    sources = {name: sha(lane / name) for name in SOURCES}
    return supervise(lane, recipe_sha=sha(lane / "recipe.json"), sources=sources,
                     hold_paths=[str(lane / "launcher.HOLD")], **capacity, admit=admit, publish=publish)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lane", type=Path)
    parser.add_argument("armed_id")
    parser.add_argument("owner", type=int)
    args = parser.parse_args()
    run(args.lane, args.armed_id, args.owner)
