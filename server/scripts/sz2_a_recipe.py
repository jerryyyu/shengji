"""Emit the SZ2-A decision recipe from the verified exports before duel admission."""
import hashlib
import json

from sz2_duel_decision import ARM, DEALS, PREDECLARE, READER_SHA, SEED0
from sz2_duel_exports import verified_exports
from sz2_duel_sides import FLEET, REFERENCE, build_sides_from_reference, load_reference


LANE = FLEET / "codex-sz2-duel-a-v1"
PREDECLARE_SHA = "0fcdc84b552a71d725def528a080d7aafa012f455e1f7086f5513670f32f20b8"


def producer_arguments(adapter, root, side):
    # The supervisor supplies the interpreter and admitted worker count.
    argv = [adapter, "--arm", "identity", "--seed0", str(SEED0), "--deals", str(DEALS),
            "--round-plan", "r2", "--out", str(root / "duel.jsonl")]
    for role in ("defender", "exploiter"):
        for word in side[f"{role}_words"]:
            argv.extend((f"--{role}-env", word))
    return argv


def decision_recipe(reference, side, lane):
    if (side["seed0"], side["deals"]) != (SEED0, DEALS):
        raise ValueError("unexpected SZ2-A decision window")
    reader = lane / "kit" / "sz2_a_read.py"
    helper = reader.with_name("ut_read.py")
    legacy_helper = str(REFERENCE.parent / "kit" / helper.name)
    for path, expected in ((reader, READER_SHA), (helper, reference["pins"][legacy_helper]),
                           (PREDECLARE, PREDECLARE_SHA)):
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"decision dependency changed: {path}")
    if lane.is_symlink() or (lane / "out").is_symlink():
        raise ValueError("decision output directory is a symlink")
    root = lane / "out" / ARM
    status = lane / f"{ARM}.status"
    for path in (root, status):
        if path.exists() or path.is_symlink():
            raise ValueError(f"decision output already exists: {path}")
    arm_pins = {side[f"{tag}_{kind}"]: side[f"{tag}_{kind}_sha256"]
                for tag in ("ex", "def") for kind in ("package", "belief")}
    arm = dict(side, pins=arm_pins, out_root=str(root), status=str(status))
    pins = dict(reference["pins"])
    del pins[str(REFERENCE.parent / "ut_run_h2h.sh")]
    pins.update({str(reader): READER_SHA, str(helper): pins[legacy_helper], str(PREDECLARE): PREDECLARE_SHA})
    adapter = str(REFERENCE.parent / "kit" / "ut_h2h_adapter.py")
    if adapter not in pins or reference["round_plan"] != "r2":
        raise ValueError("expected the pinned paired adapter and rank-mixed r2 plan")
    argv = producer_arguments(adapter, root, side)
    recipe = {k: reference[k] for k in ("schema", "duel", "round_plan", "r52_words", "tree", "tree_head")}
    return dict(recipe, reader=str(reader), reader_sha256=READER_SHA, pins=pins,
                producer_argv=argv, predeclare_sha256=PREDECLARE_SHA, arms={ARM: arm})


if __name__ == "__main__":
    reference = load_reference()
    arm = build_sides_from_reference(verified_exports(), reference)[ARM]
    print(json.dumps(decision_recipe(reference, arm, LANE), sort_keys=True))
