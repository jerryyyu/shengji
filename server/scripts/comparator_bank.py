#!/usr/bin/env python3
"""Comparator bank: sealed comparator windows a later lane may reuse instead of re-running.

A screen lane plays its comparator (the served release) against the common control on
its own fresh seeds although the comparator's windows are a deterministic function of
(seed, identity): the same identity on the same seed gives the same shards.  The bank
pins a set of sealed comparator windows under ONE identity so a reader in bank mode can
take the comparator windows for a lane's seeds from it, after an identity check.

``build``   writes a manifest (``claude-comparator-bank-v1``) over sealed window
            directories: the shared identity (arm policy, its identity object, the
            deadline recipe, the recorded environment, the package, every other harness
            leaf of config.json), and per window its seed, tree digest
            (``source_sha256``), config / summary hashes, a digest over the cluster
            shards and the per-cluster outcome digest.  Windows that disagree on the
            identity are refused.
``verify``  re-hashes every pinned file of every window: the bank bytes are unchanged.
``check``   verifies a candidate lane's frozen comparator identity
            (``claude_<lane>_expected_cmp.json``, optionally its full frozen config)
            against the bank and the seeds it needs; ANY drift refuses (package, tree,
            environment, config leaf, deadline), reported leaf by leaf.  A replay
            witness (``replay``) made on the lane's tree with the lane's identity may
            waive exactly two kinds of drift: the tree digest, and config leaves ADDED at
            the lane's side (a new rule flag at its default); a changed or removed leaf,
            an environment or package difference is never waived.
``replay``  re-runs k clusters of bank windows on THIS tree with the lane's frozen
            comparator identity and writes the witness: equal ``history_sha256`` on
            every mirror, or not.

Exit status: 0 when the mode passed; 1 on a refusal; 2 when an input cannot be read.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
from pathlib import Path

SCHEMA = "claude-comparator-bank-v1"
REPLAY_SCHEMA = "claude-comparator-bank-replay-v1"
EXPECTED_SCHEMA = "claude-expected-window-identity-v1"
#: config.json keys that vary per window or per host without changing what was played
VOLATILE = ("seed0", "runtime", "source_sha256", "execution_order")
#: the identity keys the lane freezes separately (claude-expected-window-identity-v1)
FROZEN = ("arm_policy", "clusters", "arm_policy_identity", "decision_deadline")
OUTCOME_FIELDS = ("cluster", "mirror", "arm_utility", "history_sha256", "banker",
                  "winner_team", "attacker_points", "level_change", "plays")


class Refusal(Exception):
    """A verified difference or a missing precondition; the mode exits 1."""


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(obj) -> str:
    return hashlib.sha256((canonical(obj) + "\n").encode()).hexdigest()


def file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise Refusal(f"cannot read {path}: {exc}") from None


def regular(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise Refusal(f"{path} is not a regular file")
    return path


def identity_of(config: dict) -> dict:
    """The bank identity a window's config.json pins: everything but the volatile keys,
    with the recorded environment and the package named separately."""
    runtime = config.get("runtime") or {}
    environment = runtime.get("environment")
    if not isinstance(environment, dict):
        raise Refusal("config.json records no runtime environment")
    frozen = {key: config.get(key) for key in FROZEN}
    if frozen["arm_policy"] is None or not isinstance(frozen["arm_policy_identity"], dict):
        raise Refusal("config.json is not a served-policy window (no arm_policy identity)")
    harness = {k: v for k, v in config.items() if k not in VOLATILE and k not in FROZEN}
    return {
        **frozen,
        "environment": dict(sorted(environment.items())),
        "package": {"path": environment.get("SHENGJI_PV_CKPT"),
                    "sha256": environment.get("SHENGJI_PV_SHA256")},
        "harness": harness,
    }


def outcome_rows(shard: dict) -> list:
    rows = []
    for record in shard.get("records", []):
        if any(key not in record for key in OUTCOME_FIELDS):
            raise Refusal(f"shard cluster {shard.get('cluster')} lacks an outcome field")
        rows.append([record[key] for key in OUTCOME_FIELDS])
    return rows


def window_entry(directory: Path, *, hash_shards: bool = True) -> dict:
    """One sealed window: its identity, pins and outcome digest (refuses an incomplete one)."""
    directory = Path(directory).resolve()
    if directory.is_symlink() or not directory.is_dir():
        raise Refusal(f"{directory} is not a window directory")
    if (directory / "failure.json").exists():
        raise Refusal(f"{directory} carries failure.json")
    config_path = regular(directory / "config.json")
    summary_path = regular(directory / "summary.json")
    config, summary = load_json(config_path), load_json(summary_path)
    if summary.get("config") != config:
        raise Refusal(f"{directory}: summary.config differs from config.json")
    clusters = config.get("clusters")
    if (summary.get("complete") is not True or summary.get("completed_clusters") != clusters
            or summary.get("requested_clusters") != clusters or summary.get("problems")
            or summary.get("refused") or type(clusters) is not int or clusters < 1):
        raise Refusal(f"{directory}: not a verified completion of {clusters} clusters")
    if type(config.get("seed0")) is not int:
        raise Refusal(f"{directory}: no integer seed0")
    source = config.get("source_sha256")
    if not isinstance(source, dict) or not source:
        raise Refusal(f"{directory}: no source_sha256 tree identity")
    identity = identity_of(config)
    shard_lines, rows, mean = [], [], 0.0
    for cluster in range(clusters):
        path = regular(directory / f"cluster-{cluster:05}.json")
        shard = load_json(path)
        if shard.get("cluster") != cluster or shard.get("seed") != config["seed0"] + cluster:
            raise Refusal(f"{path}: cluster/seed do not match the window")
        if hash_shards:
            shard_lines.append(f"{path.name} {file_sha256(path)}\n")
        window_rows = outcome_rows(shard)
        if [r[1] for r in window_rows] != [0, 1] or any(r[0] != cluster for r in window_rows):
            raise Refusal(f"{path}: not one record per mirror")
        rows.extend(window_rows)
        mean += sum(r[2] for r in window_rows)
    return {
        "name": directory.name, "directory": str(directory), "seed0": config["seed0"],
        "clusters": clusters,
        "tree_sha256": digest(source), "tree_files": len(source),
        "runtime": {"python": (config.get("runtime") or {}).get("python"),
                    "platform": (config.get("runtime") or {}).get("platform")},
        "config_sha256": file_sha256(config_path), "summary_sha256": file_sha256(summary_path),
        "shards_sha256": hashlib.sha256("".join(shard_lines).encode()).hexdigest() if hash_shards else None,
        "outcome_sha256": digest(rows),
        "outcome": {"rounds": len(rows), "mean_arm_utility": mean / len(rows)},
        "identity_sha256": digest(identity),
        "_identity": identity,
    }


def build(args) -> int:
    out = Path(args.out)
    if out.exists():
        raise Refusal(f"{out} exists; the bank is written once")
    entries, identity = [], None
    for directory in args.window:
        entry = window_entry(Path(directory))
        own = entry.pop("_identity")
        if identity is None:
            identity = own
        elif own != identity:
            drift = identity_drift(identity, own)
            raise Refusal(f"{directory} disagrees with the first window's identity: {canonical(drift)}")
        entries.append(entry)
    seeds = [e["seed0"] for e in entries]
    if len(set(seeds)) != len(seeds):
        raise Refusal("two windows share a seed0")
    entries.sort(key=lambda e: e["seed0"])
    trees = {}
    for entry in entries:
        trees.setdefault(entry["tree_sha256"], {"windows": 0, "files": entry["tree_files"]})["windows"] += 1
    manifest = {
        "schema": SCHEMA,
        "created_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "identity": identity, "identity_sha256": digest(identity),
        "trees": trees, "windows": entries,
        "seeds": [e["seed0"] for e in entries],
    }
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(f"bank {out}: {len(entries)} windows, identity {manifest['identity_sha256'][:16]}, "
          f"{len(trees)} tree(s), sha256 {file_sha256(out)}")
    return 0


def load_bank(path: Path) -> dict:
    bank = load_json(regular(Path(path)))
    if bank.get("schema") != SCHEMA or digest(bank.get("identity")) != bank.get("identity_sha256"):
        raise Refusal(f"{path} is not a {SCHEMA} manifest or its identity digest is wrong")
    windows = bank.get("windows")
    if not isinstance(windows, list) or not windows:
        raise Refusal(f"{path} holds no windows")
    return bank


def verify(args) -> int:
    bank = load_bank(Path(args.bank))
    for window in bank["windows"]:
        entry = window_entry(Path(window["directory"]))
        entry.pop("_identity")
        if entry != window:
            diff = {k: (window.get(k), entry.get(k)) for k in set(window) | set(entry) if window.get(k) != entry.get(k)}
            raise Refusal(f"{window['directory']} changed since the bank was built: {canonical(diff)}")
        if entry["identity_sha256"] != bank["identity_sha256"]:
            raise Refusal(f"{window['directory']} no longer carries the bank identity")
    print(f"bank verified: {len(bank['windows'])} windows unchanged, identity {bank['identity_sha256'][:16]}")
    return 0


def leaf_paths(obj, prefix=()):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from leaf_paths(value, prefix + (key,))
    else:
        yield prefix, obj


def identity_drift(bank_identity: dict, lane_identity: dict) -> dict:
    """Leaf by leaf: what the lane adds, removes or changes against the bank."""
    bank_leaves = dict(leaf_paths(bank_identity))
    lane_leaves = dict(leaf_paths(lane_identity))
    added = {".".join(map(str, p)): v for p, v in lane_leaves.items() if p not in bank_leaves}
    removed = {".".join(map(str, p)): v for p, v in bank_leaves.items() if p not in lane_leaves}
    changed = {".".join(map(str, p)): {"bank": bank_leaves[p], "lane": v}
               for p, v in lane_leaves.items() if p in bank_leaves and bank_leaves[p] != v}
    return {"added": added, "removed": removed, "changed": changed}


def lane_identity_from(expected: dict, config: dict | None) -> dict:
    """The lane's comparator identity in the bank's shape, from its frozen expected-identity
    file and, when given, its frozen full config (which adds the harness leaves, the thread
    keys of the environment and the tree)."""
    if expected.get("schema") != EXPECTED_SCHEMA:
        raise Refusal(f"the expected identity is not a {EXPECTED_SCHEMA} file")
    environment = expected.get("environment")
    if not isinstance(environment, dict):
        raise Refusal("the expected identity carries no environment")
    if config is not None:
        if any(config.get(key) != expected.get(key) for key in FROZEN):
            raise Refusal("the frozen config and the expected identity disagree on the frozen keys")
        own = identity_of(config)
        recorded = {k: v for k, v in own["environment"].items() if k.startswith("SHENGJI_")}
        if recorded != environment:
            raise Refusal("the frozen config's SHENGJI_* environment differs from the expected identity's")
        return own
    return {**{key: expected.get(key) for key in FROZEN},
            "environment": dict(sorted(environment.items())),
            "package": {"path": environment.get("SHENGJI_PV_CKPT"), "sha256": environment.get("SHENGJI_PV_SHA256")},
            "harness": None}


def compare_identity(bank: dict, lane: dict, *, partial: bool) -> dict:
    """Drift between the bank identity and the lane's; ``partial`` (no full config) compares
    only the frozen keys, the SHENGJI_* environment and the package."""
    bank_identity = dict(bank["identity"])
    lane_identity = dict(lane)
    if partial:
        bank_identity.pop("harness")
        lane_identity.pop("harness")
        bank_identity["environment"] = {k: v for k, v in bank_identity["environment"].items() if k.startswith("SHENGJI_")}
    return identity_drift(bank_identity, lane_identity)


def waivable(drift: dict, lane_identity: dict) -> bool:
    """Only leaves ADDED under the policy identity's config object (a new rule flag) may
    be waived by a replay witness; anything else is a refusal with no appeal."""
    if drift["removed"] or drift["changed"] or not drift["added"]:
        return False
    return all(path.startswith("arm_policy_identity.config.") for path in drift["added"])


def check(args) -> int:
    bank = load_bank(Path(args.bank))
    expected = load_json(regular(Path(args.expected)))
    config = None
    if args.configs:
        configs = load_json(regular(Path(args.configs)))
        if not isinstance(configs, list) or not configs:
            raise Refusal("the frozen configs file is not a list of window configs")
        config = configs[args.comparator_index]
    lane = lane_identity_from(expected, config)
    drift = compare_identity(bank, lane, partial=config is None)
    refusals, waived = [], []
    identity_ok = not (drift["added"] or drift["removed"] or drift["changed"])
    witness = None
    if args.replay_witness:
        witness = load_json(regular(Path(args.replay_witness)))
        if (witness.get("schema") != REPLAY_SCHEMA or witness.get("bank_sha256") != file_sha256(Path(args.bank))
                or witness.get("expected_sha256") != file_sha256(Path(args.expected))):
            raise Refusal("the replay witness was not made for this bank and this expected identity")
        if witness.get("all_equal") is not True or not witness.get("clusters"):
            raise Refusal("the replay witness holds an unequal or empty replay; it waives nothing")
    if not identity_ok:
        if witness is not None and waivable(drift, lane):
            waived.append({"kind": "added config leaves at the lane's side", "leaves": drift["added"]})
        else:
            refusals.append({"kind": "identity drift", "drift": drift})
    # the tree: every bank window's tree must be the lane's, or witnessed on the lane's tree
    lane_tree = digest(config["source_sha256"]) if config is not None else None
    if lane_tree is None:
        refusals.append({"kind": "tree not checked", "why": "no --configs: the lane tree digest is unknown"})
    else:
        witnessed = set()
        if witness is not None:
            if witness.get("tree_sha256") != lane_tree:
                raise Refusal("the replay witness was made on another tree than the lane's frozen config")
            by_dir = {w["directory"]: w["tree_sha256"] for w in bank["windows"]}
            witnessed = {by_dir[c["directory"]] for c in witness["clusters"] if c["directory"] in by_dir}
        for tree, info in bank["trees"].items():
            if tree == lane_tree:
                continue
            if tree in witnessed:
                waived.append({"kind": "tree drift", "bank_tree": tree, "windows": info["windows"],
                               "witness_clusters": sum(1 for c in witness["clusters"] if by_dir.get(c["directory"]) == tree)})
            else:
                refusals.append({"kind": "tree drift", "bank_tree": tree, "lane_tree": lane_tree, "windows": info["windows"]})
    # the seeds the lane needs
    seeds = sorted(args.seed or [])
    held = {w["seed0"]: w for w in bank["windows"]}
    missing = [s for s in seeds if s not in held]
    if missing:
        refusals.append({"kind": "missing seeds", "seeds": missing})
    report = {
        "bank": str(args.bank), "bank_sha256": file_sha256(Path(args.bank)),
        "bank_identity_sha256": bank["identity_sha256"],
        "lane_identity_sha256": digest(lane), "partial": config is None,
        "lane_tree_sha256": lane_tree, "drift": drift, "waived": waived, "refusals": refusals,
        "seeds": {s: held[s]["directory"] for s in seeds if s in held},
        "verdict": "REFUSE" if refusals else "PASS",
    }
    print(json.dumps(report, indent=1, sort_keys=True))
    return 1 if refusals else 0


def replay(args) -> int:
    """Re-run clusters of bank windows on this tree with the lane's frozen comparator identity."""
    bank = load_bank(Path(args.bank))
    expected = load_json(regular(Path(args.expected)))
    if expected.get("schema") != EXPECTED_SCHEMA:
        raise Refusal(f"the expected identity is not a {EXPECTED_SCHEMA} file")
    environment = dict(expected["environment"])
    overrides = {}
    for item in args.env or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise Refusal(f"--env needs KEY=VALUE, not {item!r}")
        overrides[key] = value
    for key in args.unset or []:
        overrides[key] = None
    for key, value in overrides.items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    package = environment.get("SHENGJI_PV_CKPT")
    if not package or not Path(package).is_file():
        raise Refusal(f"the package {package!r} is not a file here (override the path with --env SHENGJI_PV_CKPT=...)")
    if file_sha256(Path(package)) != environment.get("SHENGJI_PV_SHA256"):
        raise Refusal("the package at SHENGJI_PV_CKPT does not hash to SHENGJI_PV_SHA256")
    for key in list(os.environ):
        if key.startswith("SHENGJI_"):
            del os.environ[key]
    os.environ.update(environment)
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from shengji.ai.registry import make_bot
    from shengji.train import cwv_shortlist_screen as screen
    from shengji.train.search_screen import execution_source_identity
    name = expected["arm_policy"]
    bot = make_bot(name, seed=0)
    identity = screen._policy_identity(bot)
    if identity != expected["arm_policy_identity"]:
        raise Refusal("this tree builds a different identity for the lane's comparator than the frozen one")
    tree = digest(execution_source_identity(Path(screen.__file__).resolve().parents[1]))
    selected = [w for w in bank["windows"] if not args.window or w["directory"] in args.window or w["name"] in args.window]
    if not selected:
        raise Refusal("no bank window selected")
    witness_rows, all_equal = [], True
    for window in selected:
        config = dict(load_json(Path(window["directory"]) / "config.json"))
        config["arm_policy"], config["arm_policy_identity"] = name, identity
        if args.no_deadline:
            config.pop("decision_deadline", None)
        for cluster in args.cluster:
            if not 0 <= cluster < window["clusters"]:
                raise Refusal(f"cluster {cluster} is outside the window")
            banked = load_json(Path(window["directory"]) / f"cluster-{cluster:05}.json")
            banked_rows = [[r["mirror"], r["history_sha256"], r["arm_utility"]] for r in banked["records"]]
            shard = screen.run_cluster(config, cluster)
            rows = [[r["mirror"], r["history_sha256"], r["arm_utility"]] for r in shard["records"]]
            equal = rows == banked_rows
            all_equal &= equal
            witness_rows.append({"directory": window["directory"], "seed0": window["seed0"], "cluster": cluster,
                                 "bank": banked_rows, "replayed": rows, "equal": equal,
                                 "wall_secs": [t["wall_secs"] for t in shard["timings"]]})
            print(f"{window['name']} cluster {cluster}: {'EQUAL' if equal else 'DIFFERENT'}", flush=True)
    witness = {
        "schema": REPLAY_SCHEMA, "bank_sha256": file_sha256(Path(args.bank)),
        "bank_identity_sha256": bank["identity_sha256"],
        "expected_sha256": file_sha256(Path(args.expected)), "arm_policy": name,
        "tree_sha256": tree, "deadline": not args.no_deadline,
        "environment_overrides": overrides, "clusters": witness_rows, "all_equal": all_equal,
        "created_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    out = Path(args.out)
    if out.exists():
        raise Refusal(f"{out} exists; a witness is written once")
    out.write_text(json.dumps(witness, indent=1, sort_keys=True) + "\n")
    print(f"replay witness {out}: {len(witness_rows)} clusters, all_equal={all_equal}, tree {tree[:16]}")
    return 0 if all_equal else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modes = parser.add_subparsers(dest="mode", required=True)
    p = modes.add_parser("build", help="write a bank manifest over sealed comparator windows")
    p.add_argument("--out", required=True)
    p.add_argument("--window", action="append", required=True, help="a sealed window directory (repeat)")
    p.set_defaults(run=build)
    p = modes.add_parser("verify", help="re-hash every pinned file of every bank window")
    p.add_argument("--bank", required=True)
    p.set_defaults(run=verify)
    p = modes.add_parser("check", help="a lane's frozen comparator identity against the bank")
    p.add_argument("--bank", required=True)
    p.add_argument("--expected", required=True, help="the lane's claude_<lane>_expected_cmp.json")
    p.add_argument("--configs", help="the lane's <lane>_expected_configs.json (adds the harness leaves and the tree)")
    p.add_argument("--comparator-index", type=int, default=-1, help="the comparator's entry in --configs (default: the last)")
    p.add_argument("--seed", type=int, action="append", help="a seed the lane needs from the bank (repeat)")
    p.add_argument("--replay-witness", help="a replay witness made on the lane's tree")
    p.set_defaults(run=check)
    p = modes.add_parser("replay", help="re-run bank clusters on this tree with the lane's comparator identity")
    p.add_argument("--bank", required=True)
    p.add_argument("--expected", required=True)
    p.add_argument("--out", required=True, help="the witness to write (never overwritten)")
    p.add_argument("--window", action="append", help="bank window directory or name (default: every window)")
    p.add_argument("--cluster", type=int, action="append", required=True, help="cluster index to replay (repeat)")
    p.add_argument("--env", action="append", help="KEY=VALUE override of the frozen environment (a local package path)")
    p.add_argument("--unset", action="append", help="a frozen environment key to drop")
    p.add_argument("--no-deadline", action="store_true", help="in-process bots instead of the deadline child")
    p.set_defaults(run=replay)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.run(args)
    except Refusal as exc:
        print(f"REFUSE: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
