"""Join a reviewed recovery source to its legacy rollout evidence audit.

Preparation only: callers must authenticate the expected configuration,
retention and pins, including the historical source-commit/run association.
This function does not grant scientific access, assign a disposition, or
produce runner input. It never constructs hashes to bless unknown evidence.
"""
from pathlib import Path

from .benchmark_legacy_evidence import SOURCE_COMMIT, audit_legacy_rollout_failure
from .benchmark_recovery_source import load_recovery_source
from .benchmark_retention import _directory, _hex, _json, _read
from .benchmark_rollout_proof import _require


def load_legacy_rollout_audit(source_directory, result_sha256, *,
                             expected_config, authenticated_retention,
                             mirror_key, pins):
    """Read only the selected mirror's accepted prompts/finals after joins.

    The forty-row report, inherited lineage and recorded costs are validated
    by the existing source reader. All evidence paths and pins are checked
    before any prompt/final is opened. Rejected transport attempts are not
    evaluator inputs and their files are not opened.
    """
    _require(type(pins) is dict and set(pins) == {
        "schema", "source_commit", "row_sha256", "calls"}
        and pins["schema"] == "benchmark-legacy-evidence-pins-v1"
        and pins["source_commit"] == SOURCE_COMMIT, "invalid legacy source pins")
    _hex(pins["row_sha256"], "mirror SHA256")
    _require(type(pins["calls"]) is dict, "invalid call pins")
    source = load_recovery_source(
        source_directory, result_sha256, expected_config=expected_config,
        authenticated_retention=authenticated_retention)
    _require(type(mirror_key) is str and mirror_key in source["source_rows"],
             "unknown recovery mirror")
    selected = source["source_rows"][mirror_key]
    row = selected["row"]
    _require("lineage" not in row, "inherited mirror is not evidence from this run")
    _require(pins["row_sha256"] == selected["sha256"], "mirror pin does not join source")
    _require(row.get("complete") is False and row.get("information") == "perfect"
             and row.get("invalid_action_feedback") is False
             and row.get("status") is None
             and type(row.get("error")) is str and row["error"].startswith("IllegalPlay:")
             and not any(key in row for key in (
                 "failure", "signed_levels", "rollout_diagnostic", "rollout_request_binding")),
             "selected mirror is not an unclassified legacy rejection")
    _require(type(row.get("arm")) is str
             and row["arm"] == f"{row['model']}-{row['information']}", "invalid arm")
    _require(type(row.get("calls")) is list, "missing call inventory")
    root = Path(source["path"])
    inventory = {}
    for call in row["calls"]:
        _require(type(call) is dict and type(call.get("accepted")) is bool,
                 "invalid accepted-call receipt")
        if not call["accepted"]:
            continue
        name = call.get("evidence_path")
        _require(type(name) is str and name not in inventory, "invalid evidence path")
        path = Path(name)
        _require(path.is_absolute() and str(path) == name, "noncanonical evidence path")
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise ValueError("evidence is outside recovery run") from exc
        parts = relative.parts
        _require(len(parts) == 5 and parts[:3] == (
            "evidence", row["arm"], f"seed-{row['seed']}-flip-{row['flip']}")
            and parts[3] in (f"seat-{row['flip']}", f"seat-{row['flip'] + 2}")
            and parts[4].startswith("call-") and len(parts[4]) > 5,
            "evidence does not belong to this mirror/model seat")
        _directory(path, "call evidence")
        inventory[name] = (path, int(parts[3][-1]))
    _require(set(inventory) == set(pins["calls"]), "accepted-call pin coverage drift")
    for binding in pins["calls"].values():
        _require(type(binding) is dict and set(binding) == {
            "prompt_sha256", "final_sha256"}, "invalid call pins")
        for digest in binding.values():
            _hex(digest, "call SHA256")

    row_bytes, row_sha = _read(Path(selected["path"]), "selected mirror")
    _require(row_sha == selected["sha256"], "mirror changed after source authentication")
    evidence = {}
    for name, (path, seat) in inventory.items():
        prompt, prompt_sha = _read(path / "prompt.txt", "legacy prompt")
        final, final_sha = _read(path / "final.json", "legacy final")
        _require(prompt_sha == pins["calls"][name]["prompt_sha256"]
                 and final_sha == pins["calls"][name]["final_sha256"], "call hash drift")
        packet = _json(prompt.partition(b"\n")[2], "legacy packet")
        _require(type(packet) is dict and type(packet.get("observation")) is dict
                 and type(packet["observation"].get("seat")) is int
                 and packet["observation"]["seat"] == seat, "evidence seat directory drift")
        evidence[name] = {"prompt_bytes": prompt, "final_bytes": final}
    audit = audit_legacy_rollout_failure(row_bytes, evidence=evidence, pins=pins)
    return {"schema": "benchmark-legacy-source-audit-v1",
            "source_pins": source["source_pins"], "mirror_key": mirror_key,
            "mirror_path": selected["path"], "recorded_costs": source["costs"],
            "audit": audit}
