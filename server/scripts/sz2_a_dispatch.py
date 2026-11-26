"""Dispatch the pinned paired producer inside the admitting supervisor's host lock."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from sz2_a_capture import destination, event, reserve, seal
from sz2_a_recipe import LANE, producer_arguments
from sz2_duel_decision import ARM, _pinned_json
from sz2_duel_sides import REFERENCE, adapter_environment, verify_tree


def dispatch(recipe_path, digest, lane, workers, supervisor_pid):
    """The caller owns admission, the process-group ceiling and the eventual UNLOCKED event."""
    recipe = _pinned_json(recipe_path, digest, "recipe")
    root, status = destination(recipe, lane)
    arm = recipe["arms"][ARM]
    reserve(recipe, digest, lane, supervisor_pid, workers)
    with status.open("a", buffering=1) as events:
        stage = "preflight"
        try:
            # Records the lock already held when this worker was dispatched.
            events.write(event("LOCKED", "after 0s (held at dispatch)"))
            tree = Path(recipe["tree"])
            verify_tree(tree, recipe["tree_head"])
            adapter = REFERENCE.parent / "kit/ut_h2h_adapter.py"
            probe = adapter.with_name("probe_names.ut.py")
            argv = recipe["producer_argv"]
            if (recipe["round_plan"] != "r2" or argv != producer_arguments(str(adapter), root, arm)
                    or any(str(path) not in recipe["pins"] for path in (adapter, probe))):
                raise ValueError("unexpected duel producer or arguments")
            expected = {arm[f"{role}_{kind}"]: arm[f"{role}_{kind}_sha256"]
                        for role in ("def", "ex") for kind in ("belief", "package")}
            if arm["pins"] != expected:
                raise ValueError("unexpected duel side pins")
            for pins in (recipe["pins"], arm["pins"]):
                for name, expected_sha in pins.items():
                    with Path(name).open("rb") as stream:
                        if hashlib.file_digest(stream, "sha256").hexdigest() != expected_sha:
                            raise ValueError(f"pin changed: {name}")
            env = adapter_environment(tree)
            roles = ("defender", "exploiter")
            stage = "names"
            names = subprocess.run([sys.executable, "-B", probe, adapter,
                                    *[",".join(arm[f"{role}_words"]) for role in roles]],
                                   stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True,
                                   cwd=tree / "server", env=env, timeout=120)
            if json.loads(names.stdout.strip().splitlines()[-1]) != [arm[f"{role}_name"] for role in roles]:
                raise ValueError("duel bot names differ from recipe")
            events.write(event("NAMES", "ok"))
            stage = "producer"
            with (root / "run.log").open("xb") as log:
                events.write(event("PRODUCER", f"workers={workers}"))
                producer = subprocess.run(["/usr/bin/time", "-l", "-o", root / "duel.time",
                                           sys.executable, "-B", *argv, "--workers", str(workers)],
                                          stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                          cwd=tree / "server", env=env)
            if producer.returncode:
                raise subprocess.CalledProcessError(producer.returncode, argv[0])
            stage = "seal"
            seal(recipe, digest, lane, producer.returncode)
        except BaseException as exc:
            rc = exc.returncode if isinstance(exc, subprocess.CalledProcessError) else 1
            events.write(event("ABORT", f"rc={rc} reason={stage}"))
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--recipe-sha256", required=True)
    parser.add_argument("--workers", type=int, required=True)
    args = parser.parse_args(argv)
    parent = os.getppid()
    owner = LANE.parent / ".claude-host.lock/owner"
    if owner.read_text().split()[:2] != [str(parent), "sz2-duel-a-v1"]:
        raise ValueError("the admitting SZ2-A supervisor must own the host lock")
    dispatch(args.recipe, args.recipe_sha256, LANE, args.workers, parent)


if __name__ == "__main__":
    main()
