#!/usr/bin/env python3
"""Score-free live-log census for promoted low-pair rollout leads.

This is an exploration-tier sourcing tool, not a strength evaluation.  It
replays only public actions, applies the treatment/null continuation rule at
each lead, and records where their actions differ.  It never reads or emits a
round winner, score, points, level change, utility, or policy outcome.

Malformed or incomplete rounds do not poison the rest of the corpus.  Every
engine-valid prefix witness is retained with an explicit prefix-completeness
flag, and each refused suffix is counted.  A later scored diagnostic may
choose to require complete rounds without throwing away the sourcing lesson.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
sys.path.insert(0, str(SERVER))

from shengji.ai.memory import Memory  # noqa: E402
from shengji.ai.pair_aware_rollout import (  # noqa: E402
    PairAwareRolloutPolicy,
)
from shengji.rl.replay_log import group_rounds, rebuild_round  # noqa: E402


SCHEMA = "pair-aware-rollout-live-census-v1"
FORBIDDEN_RESULT_KEYS = frozenset({
    "winner", "winner_team", "won", "points", "attacker_points",
    "level_change", "level_utility", "utility", "outcome", "outcomes",
})


class CensusRefused(RuntimeError):
    """A source or output cannot support the exploration claim."""


def sha256(path: os.PathLike | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def action_key(cards) -> tuple[str, ...]:
    return tuple(sorted(str(card) for card in cards))


def phase_band(hand_size: int) -> str:
    if hand_size >= 18:
        return "early"
    if hand_size >= 9:
        return "mid"
    return "late"


def _score_free_problems(value: object, path: str = "") -> list[str]:
    problems = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_RESULT_KEYS:
                problems.append(f"forbidden result field {path}{key}")
            problems.extend(_score_free_problems(child, f"{path}{key}."))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            problems.extend(_score_free_problems(child, f"{path}{index}."))
    return sorted(set(problems))


def _lead_witness(rnd, *, source_sha256: str, source_name: str,
                  round_no: int, event_index: int, actor_is_bot: bool | None,
                  observed_action, prefix_complete: bool) -> dict | None:
    seat = rnd.turn
    if seat is None or rnd.trick is None or rnd.trick.plays:
        return None
    treatment = PairAwareRolloutPolicy(apply_treatment=True)
    null = PairAwareRolloutPolicy(apply_treatment=False)
    proposed = treatment.decide_play(rnd, seat)
    baseline = null.decide_play(rnd, seat)
    tr = treatment.pair_aware_telemetry()
    nr = null.pair_aware_telemetry()
    comparable = {
        key: value for key, value in tr.items()
        if key not in {"mode", "changes", "matched_noops"}
    }
    null_comparable = {
        key: value for key, value in nr.items()
        if key not in {"mode", "changes", "matched_noops"}
    }
    if comparable != null_comparable:
        raise CensusRefused("treatment/null lead analysis work drift")
    if tr["triggers"] == 0:
        return None
    if (tr["triggers"] != tr["changes"] or nr["triggers"] != 1
            or nr["matched_noops"] != 1
            or action_key(proposed) == action_key(baseline)):
        raise CensusRefused("trigger does not carry exact treatment/null dose")

    memory = Memory(rnd, seat)
    pair_code = proposed[0]
    suit = rnd.ordering.eff_suit(pair_code)
    opponents = [other for other in range(4) if other % 2 != seat % 2]
    public_pair_caps = {
        str(other): memory.max_pairs(other, suit) for other in opponents
    }
    state_id = stable_digest({
        "source_sha256": source_sha256,
        "round": round_no,
        "event_index": event_index,
        "seat": seat,
    })
    observed = action_key(observed_action)
    proposed_key = action_key(proposed)
    baseline_key = action_key(baseline)
    return {
        "schema": "pair-aware-rollout-live-witness-v1",
        "state_id": state_id,
        "source": source_name,
        "source_sha256": source_sha256,
        "round": round_no,
        "event_index": event_index,
        "seat": seat,
        "actor_is_bot": actor_is_bot,
        "role": "attacker" if rnd.is_attacker(seat) else "defender",
        "phase": phase_band(len(rnd.hands[seat])),
        "hand_size": len(rnd.hands[seat]),
        "baseline_action": list(baseline_key),
        "proposed_action": list(proposed_key),
        "observed_action": list(observed),
        "observed_matches_baseline": observed == baseline_key,
        "observed_matches_proposed": observed == proposed_key,
        "pair_effective_suit": suit,
        "public_pair_is_boss": memory.pair_is_boss(pair_code),
        "public_pair_caps": public_pair_caps,
        "opponent_voids": {
            str(other): sorted(memory.voids[other]) for other in opponents
        },
        "valid_prefix": True,
        "round_replay_complete": prefix_complete,
        "strength_evidence": False,
    }


def scan_source(path: Path) -> tuple[Counter, list[dict], dict]:
    source_sha = sha256(path)
    try:
        grouped = group_rounds(str(path))
    except Exception as exc:
        raise CensusRefused(
            f"cannot group {path}: {type(exc).__name__}: {exc}") from exc
    totals = Counter()
    witnesses: list[dict] = []
    refusal_examples: dict[str, list[int]] = {}
    for round_no, events in sorted(grouped.items()):
        totals["rounds_seen"] += 1
        start = next((event for event in events
                      if event.get("e") == "round_start"), None)
        players = start.get("players") if isinstance(start, dict) else None
        actor_types = {
            int(player["seat"]): bool(player.get("is_bot"))
            for player in players or []
            if isinstance(player, dict) and isinstance(player.get("seat"), int)
        }
        try:
            rnd = rebuild_round(events)
        except Exception as exc:
            reason = f"setup_{type(exc).__name__}"
            totals[f"rounds_refused_{reason}"] += 1
            refusal_examples.setdefault(reason, []).append(round_no)
            continue
        if rnd is None:
            totals["rounds_refused_missing_setup"] += 1
            refusal_examples.setdefault("missing_setup", []).append(round_no)
            continue

        local: list[dict] = []
        problem: str | None = None
        for event_index, event in enumerate(events):
            if event.get("e") != "play":
                continue
            if rnd.phase != "play":
                problem = "play_outside_play_phase"
                break
            seat, cards = event.get("seat"), event.get("cards")
            if (isinstance(seat, bool) or not isinstance(seat, int)
                    or seat != rnd.turn or not isinstance(cards, list)):
                problem = "play_turn_or_shape"
                break
            if rnd.trick is not None and not rnd.trick.plays:
                totals["lead_states_seen"] += 1
                try:
                    witness = _lead_witness(
                        rnd, source_sha256=source_sha,
                        source_name=path.name, round_no=int(round_no),
                        event_index=event_index,
                        actor_is_bot=actor_types.get(seat),
                        observed_action=cards,
                        prefix_complete=False)
                except Exception as exc:
                    problem = f"lead_analysis_{type(exc).__name__}"
                    break
                if witness is not None:
                    local.append(witness)
            try:
                rnd.play(seat, list(cards))
            except Exception as exc:
                problem = f"play_{type(exc).__name__}"
                break

        complete = problem is None and rnd.phase == "round_end"
        if complete:
            totals["rounds_replayed_complete"] += 1
        else:
            reason = problem or "incomplete_prefix"
            totals[f"rounds_prefix_only_{reason}"] += 1
            refusal_examples.setdefault(reason, []).append(round_no)
        for witness in local:
            witness["round_replay_complete"] = complete
            witnesses.append(witness)
            totals["trigger_states"] += 1
            totals[f"trigger_phase_{witness['phase']}"] += 1
            totals[f"trigger_role_{witness['role']}"] += 1
            actor = "bot" if witness["actor_is_bot"] else "human"
            totals[f"trigger_actor_{actor}"] += 1
            if witness["observed_matches_proposed"]:
                totals["trigger_observed_proposed"] += 1
                totals[f"trigger_{actor}_observed_proposed"] += 1
            elif witness["observed_matches_baseline"]:
                totals["trigger_observed_baseline"] += 1
                totals[f"trigger_{actor}_observed_baseline"] += 1
            else:
                totals["trigger_observed_other"] += 1
                totals[f"trigger_{actor}_observed_other"] += 1
            if not complete:
                totals["trigger_states_from_valid_prefix"] += 1

    return totals, witnesses, {
        reason: values[:3] for reason, values in sorted(refusal_examples.items())
    }


def build_census(paths: list[Path]) -> dict:
    if not paths:
        raise CensusRefused("at least one source is required")
    totals = Counter()
    witnesses: list[dict] = []
    sources = []
    refusals = {}
    seen_sha = set()
    for path in sorted({item.resolve() for item in paths}):
        if not path.is_file():
            raise CensusRefused(f"source is not a file: {path}")
        digest = sha256(path)
        if digest in seen_sha:
            raise CensusRefused("duplicate source bytes under multiple paths")
        seen_sha.add(digest)
        local_totals, local_witnesses, local_refusals = scan_source(path)
        totals.update(local_totals)
        witnesses.extend(local_witnesses)
        sources.append({
            "name": path.name, "sha256": digest, "bytes": path.stat().st_size,
        })
        if local_refusals:
            refusals[path.name] = local_refusals
    witnesses.sort(key=lambda row: (
        row["source_sha256"], row["round"], row["event_index"], row["seat"]))
    payload = {
        "schema": SCHEMA,
        "score_free": True,
        "outcomes_opened": False,
        "strength_evidence": False,
        "partial_valid_prefixes_retained": True,
        "sources": sources,
        "counts": dict(sorted(totals.items())),
        "refusal_examples": refusals,
        "witnesses": witnesses,
    }
    problems = _score_free_problems(payload)
    if problems:
        raise CensusRefused("; ".join(problems))
    payload["internal_sha256"] = stable_digest(payload)
    return payload


def write_exclusive(path: Path, payload: dict) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise CensusRefused("refusing to overwrite census artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
           + "\n").encode()
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.link(partial, path)
    partial.unlink()
    if json.loads(path.read_bytes()) != payload:
        raise CensusRefused("census failed exact reopen")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sources", nargs="+")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    payload = build_census([Path(source) for source in args.sources])
    write_exclusive(Path(args.out), payload)
    print(json.dumps({
        "status": "COMPLETE_SCORE_FREE_EXPLORATION",
        "sources": len(payload["sources"]),
        "counts": payload["counts"],
        "output_sha256": sha256(args.out),
        "internal_sha256": payload["internal_sha256"],
        "strength_evidence": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
