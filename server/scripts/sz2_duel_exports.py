"""Resolve the completed SZ2 exports and the fixed FT500 duel control."""
import json
import re

from sz2_cache_arm import FLEET, JOINT, RECIPE, RECIPE_SHA, arm_inputs
from sz2_export_arm import EXPORT, PARITY_ROWS, POLISH, TEMPERATURE, check_parity, selected_checkpoint


FT500 = FLEET / "claude-ft500/cand"
FT500_PACKAGE_SHA = "cb0394f13ae8951ffb9e75b3938f0b73037baf78b4b49b041cd6de9d0317a9b5"
FT500_BELIEF_SHA = "05a928b78bf8c2ae96e1b6750a2024b115b934888ce2696a0235857a89640eda"


def _require_post_done(arm):
    lane = f"sz2-post-{arm}-v1"
    status = (FLEET / f"codex-{lane}/capture/launcher.status").read_text().splitlines()
    lock = re.escape(str(FLEET / ".claude-host.lock"))
    if status and re.fullmatch(rf"LANE UNLOCKED {lane} \S+ {lock}", status[-1]):
        status.pop()
    if not status or not re.fullmatch(rf"LANE DONE {lane} \S+ selected package parity verified rc=0", status[-1]):
        raise ValueError(f"{arm} post lane did not complete successfully")


def _load_pair(directory, package_sha, belief_sha):
    from shengji.ai.belief_numpy import load_belief_numpy
    from shengji.ai.unified_readout_numpy import load_unified_readout_numpy

    for digest in (package_sha, belief_sha):
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"{directory}: missing or invalid export SHA-256")
    package = directory / "cand.npz"
    belief = directory / "cand-belief.npz"
    model = load_unified_readout_numpy(package, sha256=package_sha)
    belief_model = load_belief_numpy(belief, sha256=belief_sha)
    if (belief_model.metadata.get("source_unified_package") != package_sha
            or model.metadata.get("temperature") != TEMPERATURE
            or belief_model.metadata.get("temperature") != TEMPERATURE):
        raise ValueError(f"{directory}: belief package does not match the unified package and temperature")
    return (str(package), package_sha, str(belief), belief_sha), model.metadata


def verified_pair(directory, selected_sha, epoch, note, parity_rows, *, root_heads=False):
    parity = json.loads((directory / "parity.json").read_text())
    if (not isinstance(parity, dict) or parity.get("selected_checkpoint_sha256") != selected_sha
            or type(parity.get("best_epoch")) is not int or parity["best_epoch"] != epoch):
        raise ValueError(f"{note} parity receipt does not match the selected checkpoint")
    package_sha = parity.get("package")
    check_parity(parity, package_sha, parity_rows, root_heads=root_heads)
    entry, metadata = _load_pair(directory, package_sha, parity.get("belief_sha256"))
    if metadata.get("source_checkpoint_sha256") != selected_sha or metadata.get("note") != note:
        raise ValueError(f"{note} unified package does not match the selected checkpoint and arm")
    return entry


def verified_exports():
    """Return the exact unified and belief paths and SHAs for each authorized duel arm."""
    for arm in ("S", "M"):
        _require_post_done(arm)
    exports = {}
    for arm in ("S", "M"):
        checkpoint, directory, _ = arm_inputs(JOINT, arm, EXPORT, RECIPE, RECIPE_SHA)
        _, selected_sha, epoch = selected_checkpoint(POLISH / arm / directory.name, checkpoint,
                                                      directory.name.split("-", 1)[0])
        exports[arm] = verified_pair(directory, selected_sha, epoch, f"SZ2 {arm}", PARITY_ROWS)
    exports["FT500"], _ = _load_pair(FT500, FT500_PACKAGE_SHA, FT500_BELIEF_SHA)
    return exports
