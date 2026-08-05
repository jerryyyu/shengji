"""Capture and merge the preregistered deep-lead raw-state reservoir.

The real artifact is 3 splits x tricks 12..19 x two leader roles x 16 rows.
Split and target trick are hash-derived before play; role is observed at the
assigned target and never steered.  The 24 pre-play (split, trick) groups are
partitioned across workers, so a deal is simulated by at most one worker and
each worker sees its groups' seeds in global ascending order.  The merge still
sorts by seed and takes the first 16, so worker completion order cannot select
the corpus without making every shard over-capture every cell.

Capture one shard (repeat for every index):

    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 uv run python \
      scripts/capture_deep_leads.py capture --shard-count 8 --shard-index 0

Merge only after all shards completed:

    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 uv run python \
      scripts/capture_deep_leads.py merge --shard-count 8

Capture produces raw setup/history only.  It never enumerates a pilot ballot,
draws scoring folds, or touches arm values; REPORT remains frozen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.registry import make_bot                       # noqa: E402
from shengji.engine.game import Game                           # noqa: E402
from shengji.state_replay import (DEEP_LEAD_STATE_SCHEMA,      # noqa: E402
                                  replay_deep_lead)

SPLITS = ("dev", "calib", "report")
TRICKS = tuple(range(12, 20))
ROLES = ("attacker", "defender")
GROUPS = tuple((split, trick) for split in SPLITS for trick in TRICKS)
PER_CELL = 16
SEED0 = 92_000_000
MAX_SEEDS = 60_000                 # exclusive: seed0 <= seed < seed0 + n
SALT = "deep-leads-v1"
BOT = "mc-strong"
SHARD_SCHEMA = "deep-lead-shard-v2"
MANIFEST_SCHEMA = "deep-lead-manifest-v2"
SPLIT_SCHEMA = "deep-lead-split-v1"
SAMPLER_COUNTER_NAMES = ("zero_world_decisions", "rejected_worlds",
                         "impossible_worlds")


def sha256_file(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_output(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def cell_targets(seed: int, salt: str) -> tuple[str, int]:
    """Split and target trick for a deal, fixed before any cards are played."""
    h = hashlib.sha256(f"{salt}|deal|{seed}".encode()).digest()
    return SPLITS[h[0] % len(SPLITS)], TRICKS[h[1] % len(TRICKS)]


def cell_name(cell: tuple[str, int, str]) -> str:
    return f"{cell[0]}/{cell[1]}/{cell[2]}"


def all_cells() -> set[tuple[str, int, str]]:
    return {(split, trick, role) for split in SPLITS for trick in TRICKS
            for role in ROLES}


def group_owner(split: str, trick: int, shard_count: int) -> int:
    """Worker owning a group known before play; roles cannot be steered."""
    return GROUPS.index((split, trick)) % shard_count


def owned_cells(cells: set[tuple[str, int, str]], shard_index: int,
                shard_count: int) -> set[tuple[str, int, str]]:
    return {cell for cell in cells
            if group_owner(cell[0], cell[1], shard_count) == shard_index}


def parse_cells(values: list[str]) -> set[tuple[str, int, str]]:
    if not values:
        return all_cells()
    out = set()
    for value in values:
        try:
            split, trick_s, role = value.split("/")
            cell = (split, int(trick_s), role)
        except (ValueError, TypeError):
            raise ValueError(f"invalid --only-cell {value!r}; use dev/12/attacker")
        if cell not in all_cells():
            raise ValueError(f"invalid --only-cell {value!r}")
        out.add(cell)
    return out


def sibling(path: str, infix: str, suffix: str) -> str:
    p = Path(path)
    stem = p.name[:-6] if p.name.endswith(".jsonl") else p.name
    return str(p.with_name(stem + infix + suffix))


def shard_path(base: str, index: int, count: int) -> str:
    return sibling(base, f".shard-{index:03d}-of-{count:03d}", ".jsonl")


def manifest_path(path: str) -> str:
    return sibling(path, "", ".manifest.json")


def split_path(base: str) -> str:
    return str(Path(base).with_name("deep_lead_split.v1.json"))


def write_json(path: str, payload: dict) -> None:
    with open(path, "x") as fh:
        json.dump(payload, fh, sort_keys=True, indent=2)
        fh.write("\n")


def source_digests() -> dict[str, str]:
    """Executable boundaries that define actor, sampler, engine and replay."""
    import shengji.ai.heuristic as heuristic
    import shengji.ai.mcbot as mcbot
    import shengji.ai.memory as memory
    import shengji.ai.registry as registry
    import shengji.ai.smart as smart
    import shengji.engine.combos as combos
    import shengji.engine.fast as fast
    import shengji.engine.legal as legal
    import shengji.engine.round as round_mod
    import shengji.state_replay as state_replay

    paths = {
        "capture": __file__, "mcbot_sampler": mcbot.__file__,
        "memory": memory.__file__, "registry": registry.__file__,
        "heuristic_rollout": heuristic.__file__, "smart_actor": smart.__file__,
        "engine_round": round_mod.__file__, "engine_legal": legal.__file__,
        "engine_combos": combos.__file__, "state_replay": state_replay.__file__,
    }
    if not fast.HAVE_FAST or fast._fast is None:
        raise RuntimeError("compiled engine is unavailable")
    paths["compiled_engine"] = fast._fast.__file__
    return {name: sha256_file(path) for name, path in sorted(paths.items())}


def runtime_contract(*, smoke: bool, bot: str, per_cell: int) -> dict:
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise RuntimeError("set SHENGJI_REQUIRE_VOIDS=1")
    if os.environ.get("SHENGJI_FAST") != "1":
        raise RuntimeError("set SHENGJI_FAST=1; compiled execution is mandatory")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise RuntimeError("SHENGJI_FAST=1 did not activate the compiled engine")
    if bot != BOT:
        raise RuntimeError(f"actor must be {BOT!r}, got {bot!r}")
    if not smoke and per_cell != PER_CELL:
        raise RuntimeError(f"real capture requires exactly {PER_CELL} per cell")
    dirty = git_output("status", "--porcelain")
    if dirty and not smoke:
        raise RuntimeError("real capture refuses a dirty tree")
    return {"git": git_output("rev-parse", "HEAD"), "tree_dirty": bool(dirty),
            "fast_engine": True, "require_voids": True}


def sampler_counters(policies) -> tuple[dict[str, int], Counter]:
    totals = {name: sum(int(getattr(bot, name, 0)) for bot in policies)
              for name in SAMPLER_COUNTER_NAMES}
    causes = Counter()
    for bot in policies:
        causes.update(getattr(bot, "reject_cause", {}))
    return totals, causes


def sampler_disposition(counters: dict[str, int]) -> str:
    """Classify one deal without weakening the accepted-path contract.

    A rejected world was never used, but its decision ran at less than the
    registered N=30 dose.  Exclude the whole trajectory and keep scanning.
    A zero-world decision did use the heuristic fallback, and an impossible
    world means a void-violating sample was used; either is a fatal contract
    failure under strict capture.
    """
    if counters.get("zero_world_decisions") or counters.get("impossible_worlds"):
        return "abort"
    if counters.get("rejected_worlds"):
        return "reject_deal"
    return "accept"


@dataclass
class DealOutcome:
    rnd: object
    seat: int | None
    setup: dict
    plays: list[dict]
    policies: list

    @property
    def reached(self) -> bool:
        return self.seat is not None


def play_to_trick(seed: int, target: int, bot_name: str = BOT) -> DealOutcome:
    """Self-play to the start of exactly ``target`` and retain replay inputs."""
    game = Game(random.Random(seed))
    rnd = game.start_round()
    policies = [make_bot(bot_name, seed=seed * 4 + seat) for seat in range(4)]
    declarations: list[dict] = []
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = policies[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({"stage": "deal", "deal_pos": rnd._deal_pos,
                                 "seat": seat, "cards": list(cards)})
    for seat in range(4):
        cards = policies[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({"stage": "final", "deal_pos": rnd._deal_pos,
                                 "seat": seat, "cards": list(cards)})
    rnd.finalize_declare()
    assert rnd.banker is not None
    buried = policies[rnd.banker].decide_bury(rnd, rnd.banker)
    final_decl = None if rnd.declaration is None else {
        "seat": rnd.declaration["seat"], "cards": list(rnd.declaration["cards"]),
        "strength": rnd.declaration["strength"],
    }
    setup = {
        "deck": list(rnd.deck), "initial_banker": None,
        "trump_rank": rnd.trump_rank, "banker": rnd.banker,
        "trump_suit": rnd.trump_suit, "trump_is_nt": rnd.trump_is_nt,
        "declarations": declarations, "final_declaration": final_decl,
        "buried": list(buried),
    }
    rnd.bury(rnd.banker, buried)
    plays: list[dict] = []
    while rnd.phase == "play":
        if (len(rnd.history) == target and rnd.trick is not None
                and not rnd.trick.plays):
            return DealOutcome(rnd, rnd.turn, setup, plays, policies)
        seat = rnd.turn
        if seat is None:
            break
        cards = policies[seat].decide_play(rnd, seat)
        # IllegalPlay and every other engine exception intentionally propagate.
        rnd.play(seat, list(cards))
        plays.append({"seat": seat, "cards": list(cards)})
    return DealOutcome(rnd, None, setup, plays, policies)


def config_for(args, cells) -> dict:
    return {
        "seed0": args.seed0, "max_seeds": args.max_seeds,
        "seed_ceiling_exclusive": args.seed0 + args.max_seeds,
        "salt": args.salt, "bot": args.bot, "per_cell": args.per_cell,
        "shard_count": args.shard_count,
        "cells": sorted(cell_name(c) for c in cells),
        "actor_seed_formula": "deal_seed * 4 + seat",
        "split_target_stream": "sha256(salt|deal|seed)",
        "sharding": "preplay_(split,trick)_group_mod_shard_count",
        "sampler_admission": (
            "exclude_deal_on_rejected_world;"
            "abort_on_zero_world_or_impossible_world"
        ),
        "report_frozen": True, "smoke": args.smoke,
    }


def capture(args) -> int:
    cells = parse_cells(args.only_cell)
    runtime = runtime_contract(smoke=args.smoke, bot=args.bot,
                               per_cell=args.per_cell)
    if not 0 <= args.shard_index < args.shard_count:
        raise RuntimeError("shard index must satisfy 0 <= index < count")
    if args.shard_count > len(GROUPS):
        raise RuntimeError(f"shard count exceeds the {len(GROUPS)} pre-play groups")
    out = shard_path(args.out, args.shard_index, args.shard_count)
    partial = out + ".partial"
    mpath = manifest_path(out)
    for path in (out, partial, mpath):
        if os.path.exists(path):
            raise RuntimeError(f"refusing to overwrite {path}")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    config = config_for(args, cells)
    digests = source_digests()
    from shengji.engine.ballot import mc_ballot
    ballot = str(mc_ballot(make_bot(args.bot, seed=1)))
    mine = owned_cells(cells, args.shard_index, args.shard_count)
    kept: dict[tuple[str, int, str], int] = {cell: 0 for cell in mine}
    reject_reasons = Counter()
    observed_sampler_totals = Counter()
    accepted_sampler_totals = Counter()
    sampler_causes = Counter()
    sampler_rejected_deals = 0
    accepted = scanned = played = 0
    last_seed = None

    with open(partial, "x") as fh:
        for seed in range(args.seed0, args.seed0 + args.max_seeds):
            scanned += 1
            last_seed = seed
            split, target = cell_targets(seed, args.salt)
            possible = [(split, target, role) for role in ROLES
                        if (split, target, role) in mine]
            if not possible:
                reject_reasons["not_owned_preplay_group"] += 1
                continue
            if all(kept[cell] >= args.per_cell for cell in possible):
                reject_reasons["local_cell_cap"] += 1
                continue

            played += 1
            result = play_to_trick(seed, target, args.bot)
            counters, causes = sampler_counters(result.policies)
            observed_sampler_totals.update(counters)
            sampler_causes.update(causes)
            disposition = sampler_disposition(counters)
            if disposition == "abort":
                fatal = {k: v for k, v in counters.items()
                         if k in ("zero_world_decisions", "impossible_worlds")
                         and v}
                raise RuntimeError(f"seed {seed} hit fatal sampler counters: "
                                   f"{fatal}")
            if disposition == "reject_deal":
                # The invalid proposal was rejected inside MCBot, but that
                # decision consequently used fewer than N=30 worlds.  Keeping
                # no state from the trajectory preserves the registered actor
                # dose without turning a rare, safely refused proposal into a
                # shard-killing event.
                sampler_rejected_deals += 1
                reject_reasons["strict_sampler_rejected_deal"] += 1
                continue
            if not result.reached:
                reject_reasons["round_ended_before_target"] += 1
                continue
            rnd, seat = result.rnd, result.seat
            assert seat is not None
            role = "attacker" if rnd.is_attacker(seat) else "defender"
            cell = (split, target, role)
            if cell not in cells:
                reject_reasons["unselected_role"] += 1
                continue
            if kept[cell] >= args.per_cell:
                reject_reasons["local_role_cap"] += 1
                continue

            row = {
                "schema": DEEP_LEAD_STATE_SCHEMA,
                "seed": seed, "split": split, "trick": target, "role": role,
                "seat": seat, "ply": len(result.plays),
                "setup": result.setup, "plays": result.plays,
            }
            # Round-trip before the row is allowed into even a shard.
            replay_deep_lead(row)
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            accepted_sampler_totals.update(counters)
            kept[cell] += 1
            accepted += 1
            if all(n >= args.per_cell for n in kept.values()):
                break  # later local seeds cannot enter the global first 16
        fh.flush()
        os.fsync(fh.fileno())

    payload = {
        "schema": SHARD_SCHEMA, **runtime, "config": config,
        "source_digests": digests, "ballot": ballot,
        "shard_index": args.shard_index, "shard_count": args.shard_count,
        "owned_cells": sorted(cell_name(cell) for cell in mine),
        "scan_complete": True,
        "stopped": ("local_cell_cap" if all(n >= args.per_cell for n in kept.values())
                    else "exclusive_seed_ceiling"),
        "scanned_seeds": scanned, "played_deals": played,
        "last_seed": last_seed, "accepted": accepted,
        "records_sha256": sha256_file(partial),
        "cell_candidates": {cell_name(c): kept[c] for c in sorted(kept)},
        "reject_reasons": dict(sorted(reject_reasons.items())),
        # `sampler_counters` retains its fail-closed meaning for trajectories
        # admitted to the artifact.  `observed_sampler_counters` separately
        # makes excluded attempts auditable instead of silently erasing them.
        "sampler_counters": {name: int(accepted_sampler_totals[name])
                             for name in SAMPLER_COUNTER_NAMES},
        "observed_sampler_counters": {
            name: int(observed_sampler_totals[name])
            for name in SAMPLER_COUNTER_NAMES
        },
        "sampler_rejected_deals": sampler_rejected_deals,
        "sampler_reject_causes": dict(sorted(sampler_causes.items())),
        "illegal_actions": 0, "engine_errors": 0, "scored_values": 0,
    }
    write_json(mpath + ".partial", payload)
    os.replace(mpath + ".partial", mpath)
    # The data path is the shard completion marker and moves last.
    os.replace(partial, out)
    print(f"wrote shard {out}: {accepted} candidates from {played} played deals "
          f"({scanned} assigned seed positions)")
    return 0


def load_jsonl(path: str) -> list[dict]:
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def select_candidates(rows: list[dict], cells: set[tuple[str, int, str]],
                      per_cell: int) -> tuple[list[dict], dict[str, int]]:
    """Global first-N selection, independent of shard or completion order."""
    by_cell = defaultdict(list)
    for row in rows:
        by_cell[(row["split"], row["trick"], row["role"])].append(row)
    selected, shortages = [], {}
    for cell in sorted(cells):
        candidates = sorted(by_cell[cell], key=lambda row: row["seed"])
        if len(candidates) < per_cell:
            shortages[cell_name(cell)] = per_cell - len(candidates)
        selected.extend(candidates[:per_cell])
    selected.sort(key=lambda row: row["seed"])
    return selected, shortages


def validate_shard(manifest: dict, rows: list[dict], args, index: int,
                   expected_config: dict, expected_runtime: dict) -> list[str]:
    problems = []
    if manifest.get("schema") != SHARD_SCHEMA:
        problems.append(f"shard {index}: schema")
    if manifest.get("shard_index") != index or manifest.get("shard_count") != args.shard_count:
        problems.append(f"shard {index}: identity")
    expected_owned = sorted(cell_name(cell) for cell in owned_cells(
        set(parse_cells(args.only_cell)), index, args.shard_count))
    if manifest.get("owned_cells") != expected_owned:
        problems.append(f"shard {index}: cell ownership")
    if manifest.get("config") != expected_config:
        problems.append(f"shard {index}: config drift")
    for key in ("git", "tree_dirty", "fast_engine", "require_voids"):
        if manifest.get(key) != expected_runtime[key]:
            problems.append(f"shard {index}: runtime {key} drift")
    if not manifest.get("scan_complete"):
        problems.append(f"shard {index}: incomplete scan")
    if manifest.get("accepted") != len(rows):
        problems.append(f"shard {index}: record count")
    if manifest.get("records_sha256") != sha256_file(shard_path(args.out, index, args.shard_count)):
        problems.append(f"shard {index}: record digest")
    if manifest.get("illegal_actions") or manifest.get("engine_errors") or manifest.get("scored_values"):
        problems.append(f"shard {index}: forbidden failure/value counter")
    accepted_counters = manifest.get("sampler_counters")
    observed_counters = manifest.get("observed_sampler_counters")
    if (not isinstance(accepted_counters, dict)
            or set(accepted_counters) != set(SAMPLER_COUNTER_NAMES)
            or any(not isinstance(v, int) or v < 0
                   for v in accepted_counters.values())):
        problems.append(f"shard {index}: accepted sampler counter schema")
    elif any(accepted_counters.values()):
        problems.append(f"shard {index}: forbidden accepted sampler fallback")
    if (not isinstance(observed_counters, dict)
            or set(observed_counters) != set(SAMPLER_COUNTER_NAMES)
            or any(not isinstance(v, int) or v < 0
                   for v in observed_counters.values())):
        problems.append(f"shard {index}: observed sampler counter schema")
    else:
        if (observed_counters["zero_world_decisions"]
                or observed_counters["impossible_worlds"]):
            problems.append(f"shard {index}: fatal observed sampler counter")
        rejected_deals = manifest.get("sampler_rejected_deals")
        recorded_rejections = manifest.get("reject_reasons", {}).get(
            "strict_sampler_rejected_deal", 0)
        if (not isinstance(rejected_deals, int) or rejected_deals < 0
                or rejected_deals != recorded_rejections
                or bool(rejected_deals) != bool(observed_counters["rejected_worlds"])
                or (isinstance(rejected_deals, int)
                    and observed_counters["rejected_worlds"] < rejected_deals)):
            problems.append(f"shard {index}: sampler rejection accounting")
    allowed = {"schema", "seed", "split", "trick", "role", "seat", "ply",
               "setup", "plays"}
    for row in rows:
        if set(row) != allowed or row.get("schema") != DEEP_LEAD_STATE_SCHEMA:
            problems.append(f"shard {index}: non-raw or wrong-schema row")
            break
        if group_owner(row["split"], row["trick"], args.shard_count) != index:
            problems.append(f"shard {index}: row outside owned pre-play group")
            break
        if (row["split"], row["trick"]) != cell_targets(row["seed"], args.salt):
            problems.append(f"shard {index}: post-hoc cell")
            break
    return problems


def merge(args) -> int:
    cells = parse_cells(args.only_cell)
    runtime = runtime_contract(smoke=args.smoke, bot=args.bot,
                               per_cell=args.per_cell)
    if args.shard_count > len(GROUPS):
        raise RuntimeError(f"shard count exceeds the {len(GROUPS)} pre-play groups")
    config = config_for(args, cells)
    final_manifest = manifest_path(args.out)
    final_split = split_path(args.out)
    for path in (args.out, final_manifest, final_split,
                 args.out + ".partial", final_manifest + ".partial",
                 final_split + ".partial"):
        if os.path.exists(path):
            raise RuntimeError(f"refusing to overwrite {path}")

    manifests, rows, problems = [], [], []
    expected_sources = None
    expected_ballot = None
    for index in range(args.shard_count):
        spath = shard_path(args.out, index, args.shard_count)
        mpath = manifest_path(spath)
        if not os.path.exists(spath) or not os.path.exists(mpath):
            problems.append(f"shard {index}: missing artifact or manifest")
            continue
        manifest = json.load(open(mpath))
        shard_rows = load_jsonl(spath)
        problems += validate_shard(manifest, shard_rows, args, index, config, runtime)
        if expected_sources is None:
            expected_sources = manifest.get("source_digests")
            expected_ballot = manifest.get("ballot")
        elif (manifest.get("source_digests") != expected_sources
              or manifest.get("ballot") != expected_ballot):
            problems.append(f"shard {index}: source/ballot drift")
        manifests.append(manifest)
        rows.extend(shard_rows)
    seeds = [row["seed"] for row in rows]
    if len(seeds) != len(set(seeds)):
        problems.append("duplicate deal seed across shards")
    declared_owners = [cell for manifest in manifests
                       for cell in manifest.get("owned_cells", [])]
    expected_owners = sorted(cell_name(cell) for cell in cells)
    if sorted(declared_owners) != expected_owners:
        problems.append("owned cells do not partition the target cells exactly")
    if problems:
        raise RuntimeError("merge refused: " + "; ".join(problems))

    for row in rows:
        replay_deep_lead(row)
    selected, shortages = select_candidates(rows, cells, args.per_cell)
    if shortages:
        raise RuntimeError(f"exclusive seed ceiling left cells short: {shortages}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    data_tmp = args.out + ".partial"
    with open(data_tmp, "x") as fh:
        for row in selected:
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    split_payload = {
        "schema": SPLIT_SCHEMA, "source": os.path.basename(args.out),
        "source_sha256": sha256_file(data_tmp), "salt": args.salt,
        "report_frozen": True,
        "assign": {str(row["seed"]): row["split"] for row in selected},
        "cells": {cell_name(cell): args.per_cell for cell in sorted(cells)},
    }
    write_json(final_split + ".partial", split_payload)
    manifest = {
        "schema": MANIFEST_SCHEMA, **runtime, "config": config,
        "source_digests": expected_sources, "ballot": expected_ballot,
        "complete": True, "accepted": len(selected), "replay_verified": len(selected),
        "records_sha256": sha256_file(data_tmp),
        "split_sha256": sha256_file(final_split + ".partial"),
        "cell_counts": {cell_name(cell): args.per_cell for cell in sorted(cells)},
        "shards": [{"index": i,
                    "records_sha256": manifests[i]["records_sha256"],
                    "accepted_candidates": manifests[i]["accepted"]}
                   for i in range(args.shard_count)],
        "sampler_counters": {
            k: sum(m["sampler_counters"][k] for m in manifests)
            for k in SAMPLER_COUNTER_NAMES
        },
        "observed_sampler_counters": {
            k: sum(m["observed_sampler_counters"][k] for m in manifests)
            for k in SAMPLER_COUNTER_NAMES
        },
        "sampler_rejected_deals": sum(
            m["sampler_rejected_deals"] for m in manifests
        ),
        "illegal_actions": 0, "engine_errors": 0, "scored_values": 0,
    }
    write_json(final_manifest + ".partial", manifest)
    # The data file is the completion marker and moves last.
    os.replace(final_split + ".partial", final_split)
    os.replace(final_manifest + ".partial", final_manifest)
    os.replace(data_tmp, args.out)
    print(f"wrote complete reservoir {args.out}: {len(selected)} replayed rows")
    print(f"wrote immutable split {final_split}")
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("capture", "merge"))
    ap.add_argument("--seed0", type=int, default=SEED0)
    ap.add_argument("--max-seeds", type=int, default=MAX_SEEDS)
    ap.add_argument("--bot", default=BOT)
    ap.add_argument("--salt", default=SALT)
    ap.add_argument("--out", default="rl_data/deep_leads.v1.jsonl")
    ap.add_argument("--per-cell", type=int, default=PER_CELL)
    ap.add_argument("--shard-index", type=int, default=0)
    ap.add_argument("--shard-count", type=int, default=1)
    ap.add_argument("--smoke", action="store_true",
                    help="engineering only: permits dirty tree/non-16 cells")
    ap.add_argument("--only-cell", action="append", default=[],
                    help="smoke only, e.g. dev/12/attacker")
    return ap


def main() -> None:
    args = parser().parse_args()
    if args.max_seeds < 0 or args.per_cell <= 0 or args.shard_count <= 0:
        raise SystemExit("max-seeds >= 0, per-cell > 0 and shard-count > 0 required")
    if args.only_cell and not args.smoke:
        raise SystemExit("--only-cell is an engineering-smoke option only")
    try:
        code = capture(args) if args.mode == "capture" else merge(args)
    except (RuntimeError, ValueError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
