"""Run and seal one SZ2-R stage under its lane supervisor."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

from sz2r_producer import argv, run_inputs
from sz2r_read_once import PAYLOADS, regular, verified
from sz2r_recipe import build


def produce(lane, mode, workers, recipe_sha, admit):
    """Return the new sealed output. The supervisor owns admission and the host lock."""
    if mode not in ("pilot", "timing", "screen") or type(workers) is not int:
        raise ValueError("invalid stage or worker count")
    lane = Path(lane)
    admit()
    recipe = json.loads(verified(lane / "recipe.json", recipe_sha))
    seed0, deals, output = run_inputs(recipe, mode, lane)
    command = argv(recipe, mode, workers, lane)
    if output != output.resolve() or os.path.lexists(output):
        raise ValueError(f"output path is already occupied or noncanonical: {output}")
    status_path = lane / f"{output.name}.status"
    with status_path.open("x", encoding="utf-8", buffering=1) as status:
        def record(state, detail):
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"UTD {state} {stamp} {detail}", file=status)

        record(
            "START",
            f"mode={output.name} arm={recipe['arm']} pid={os.getpid()} "
            f"seed0={seed0} deals={deals} workers={workers} recipe={recipe_sha}",
        )
        try:
            admit()
            record("LOCKED", "after 0s (under the lane supervisor's lock)")
            if build() != recipe:
                raise ValueError("live recipe differs from the pinned recipe")
            record("NAMES", "ok")
            output.parent.mkdir(exist_ok=True)
            output.mkdir()
            with (output / "run.log").open("xb") as log:
                admit()
                record("PRODUCER", "pinned identity adapter")
                subprocess.run(
                    ["/usr/bin/nice", "-n", "10", "/usr/bin/time", "-l", "-o", str(output / "duel.time"),
                     *command],
                    cwd=Path(recipe["tree"]) / "server", env=recipe["environment"],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, check=True,
                )
            manifest = dict(schema="utd-manifest-r1", mode=output.name, arm=recipe["arm"],
                            recipe_sha256=recipe_sha, seed0=seed0, deals=deals,
                            tree_head=recipe["head"], rc=0)
            with (output / "manifest.json").open("x", encoding="utf-8") as stream:
                json.dump(manifest, stream, sort_keys=True)
                stream.write("\n")
            if {path.name for path in output.iterdir()} != PAYLOADS:
                raise ValueError("unexpected producer file set")
            seals = []
            rows = 0
            for name in sorted(PAYLOADS):
                with regular(output / name).open("rb") as stream:
                    if name == "duel.jsonl":
                        digest = hashlib.sha256()
                        last_byte = b""
                        while chunk := stream.read(1024 * 1024):
                            digest.update(chunk)
                            rows += chunk.count(b"\n")
                            last_byte = chunk[-1:]
                        if last_byte != b"\n":
                            raise ValueError("duel output has no final newline")
                    else:
                        digest = hashlib.file_digest(stream, "sha256")
                seals.append(f"{digest.hexdigest()}  ./{name}\n")
            if rows != 2 * deals:
                raise ValueError(f"expected {2 * deals} producer rows, found {rows}")
            admit()
            sums = "".join(seals).encode()
            with (output / "SHA256SUMS").open("xb") as stream:
                stream.write(sums)
            record("DONE", f"recipe={recipe_sha} rows={rows} sums={hashlib.sha256(sums).hexdigest()} rc=0")
        except Exception as exc:
            record("ABORT", f"rc=4 reason={type(exc).__name__}")
            raise
        finally:
            record("UNLOCKED", "(lock held by the lane supervisor)")
    return output
