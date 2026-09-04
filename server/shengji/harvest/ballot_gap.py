"""Ballot-gap report: how often a teacher's action lies OUTSIDE the
production ballot (``MCBot._candidates`` of ``mc-s0-report-lcb``).

Sources
-------
* luna-rpc trajectories: ``action`` vs ``production_prior`` (recorded by the
  runtime at every decision).
* Sol0 / Luna0 transcripts (``shengji-ptsol0-*``, ``shengji-ptluna0-*``):
  each ``play`` request names the candidate index of the last ``observe``
  with the same ``decision_sha256``; the candidate carries
  ``in_production_ballot``.
* human_v8: every pointer's state is rebuilt and the human's action is
  tested against (a) the production ballot computed now (same
  ``c0._production_ballot`` rule: tractor-locked leads collapse to the
  heuristic pick) and (b) the corpus' own ballot
  ``rl.actions.enumerate_actions(exhaustive_follows=True, include_throws=True)``
  — the latter reproduces the manifest's ``play_actions_off_ballot`` (25).

Breakdowns: overall, by phase (lead / follow; bury decisions do not occur in
these teacher sources — stated explicitly), by trump rank, by trump mode
(suit letter or NT) and by rank|mode.  Fractions are over CONTESTED decisions
(ballot size > 1) with the all-decision count reported beside them.
"""

from __future__ import annotations

import glob
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Iterator

from .common import (HUMAN_V8, LUNA0_ROOT, LUNA_ROOTS, REPO, SOL0_ROOT,
                     InputRegistry, action_key, trump_mode)
from .legal import clone_for_probe
from .luna_rpc import iter_decisions_for_gap
from .room_log import read_rounds
from .rebuild import actor_role
from ..rl.replay_log import rebuild_round

PRODUCTION_POLICY = "mc-s0-report-lcb"
TRANSCRIPT_SCHEMAS = ("privileged-teacher-sol0-private-transcript-v1",)


# ------------------------------------------------------------ aggregation

def _cell() -> dict:
    return {"decisions": 0, "contested": 0, "off_ballot": 0}


def _finish(cell: dict) -> dict:
    n = cell["contested"]
    cell["off_ballot_fraction"] = (cell["off_ballot"] / n) if n else None
    return cell


def aggregate(decisions: Iterable[dict]) -> dict:
    """``decisions``: dicts with phase, rank, mode, contested, off_ballot."""
    overall = _cell()
    by_phase: dict[str, dict] = defaultdict(_cell)
    by_rank: dict[str, dict] = defaultdict(_cell)
    by_mode: dict[str, dict] = defaultdict(_cell)
    by_rank_mode: dict[str, dict] = defaultdict(_cell)
    for d in decisions:
        cells = (overall, by_phase[d["phase"]], by_rank[str(d["rank"])],
                 by_mode[d["mode"]], by_rank_mode[f"{d['rank']}|{d['mode']}"])
        for cell in cells:
            cell["decisions"] += 1
            if d["contested"]:
                cell["contested"] += 1
                if d["off_ballot"]:
                    cell["off_ballot"] += 1
    for phase in ("lead", "follow", "bury"):
        by_phase.setdefault(phase, _cell())
    return {
        "overall": _finish(overall),
        "by_phase": {k: _finish(v) for k, v in sorted(by_phase.items())},
        "by_rank": {k: _finish(v) for k, v in sorted(by_rank.items())},
        "by_mode": {k: _finish(v) for k, v in sorted(by_mode.items())},
        "by_rank_mode": {k: _finish(v) for k, v in sorted(by_rank_mode.items())},
    }


# ---------------------------------------------------------------- luna-rpc

def luna_rpc_decisions(registry: InputRegistry) -> Iterator[dict]:
    for d in iter_decisions_for_gap(LUNA_ROOTS, registry):
        yield {"phase": d["phase"], "rank": d["rank"], "mode": d["mode"],
               "contested": d["contested"],
               "off_ballot": d["action"] not in d["production_ballot"]}


# ------------------------------------------------------------- transcripts

def transcript_decisions(root: Path, registry: InputRegistry) -> Iterator[dict]:
    """Decisions of one Sol0/Luna0 evidence root (52 transcripts)."""
    for path in sorted(glob.glob(str(Path(root) / "*.json"))):
        doc = registry.read_json(path)
        transcript = doc["transcript"]
        if transcript.get("schema") not in TRANSCRIPT_SCHEMAS:
            raise ValueError(f"{path}: transcript schema drift")
        if transcript["status"].get("status") != "round_end":
            continue
        observed: dict[str, dict] = {}
        for event in transcript["events"]:
            op = event["operation"]
            if op == "observe":
                resp = event["response"]
                if resp.get("status") == "decision":
                    observed[resp["decision_sha256"]] = resp
            elif op == "play":
                req = event["request"]
                obs = observed[req["decision_sha256"]]
                cand = obs["candidates"][req["candidate_index"]]
                if event["response"].get("candidate_cards") != cand["cards"]:
                    raise ValueError(f"{path}: play/candidate drift")
                yield {
                    "phase": "lead" if not obs["current_trick"]["plays"] else "follow",
                    "rank": obs["trump_rank"],
                    "mode": trump_mode(obs.get("trump_suit"), obs.get("trump_is_nt")),
                    "contested": len(obs["candidates"]) > 1,
                    "off_ballot": not cand["in_production_ballot"],
                    "candidate_zero": bool(cand.get("is_candidate_zero")),
                }


# ------------------------------------------------------------------ human

def production_ballot(rnd, seat: int) -> set[tuple[str, ...]]:
    """``c0._production_ballot`` rule for the production policy."""
    from ..ai.registry import make_bot
    from ..engine.combos import decompose
    bot = make_bot(PRODUCTION_POLICY, seed=0)
    if bot.TRACTOR_LOCK and not rnd.trick.plays:
        pick = bot.canonical_lead(rnd, seat)
        dec = decompose(pick, rnd.ordering)
        if len(dec.components) == 1 and dec.components[0].pair_len >= 2:
            return {action_key(pick)}
    return {action_key(a) for a in bot._candidates(rnd, seat)}


def human_v8_ballot(rnd, seat: int) -> set[tuple[str, ...]]:
    from ..rl.actions import enumerate_actions
    return {action_key(a) for a in enumerate_actions(
        rnd, seat, exhaustive_follows=True, include_throws=True)}


def human_decisions(registry: InputRegistry, human_dir: Path = HUMAN_V8,
                    repo: Path = REPO) -> tuple[list[dict], dict]:
    manifest = registry.read_json(human_dir / "manifest.json")
    pointers = list(registry.read_jsonl(human_dir / "play_decisions.jsonl"))
    by_round: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in pointers:
        by_round[(row["source"], int(row["round"]))].append(row)
    cache: dict[str, dict[int, list[dict]]] = {}
    out: list[dict] = []
    agree = disagree = 0
    for (name, round_no), rows in sorted(by_round.items()):
        if name not in cache:
            path = next(p for p in (repo / "logs" / name,
                                    *sorted((repo / "logs" / "archive").glob(f"*/{name}")),
                                    repo / "logs" / "local" / name) if p.is_file())
            cache[name], _ = read_rounds(path, registry)
        events = cache[name][round_no]
        wanted = {int(r["event_index"]): r for r in rows}
        rnd = rebuild_round(events)
        start = next(e for e in events if e["e"] == "round_start")
        mode = trump_mode(rnd.trump_suit, rnd.trump_is_nt)
        for event_index, event in enumerate(events):
            if event.get("e") != "play" or rnd.phase != "play":
                continue
            seat = int(event["seat"])
            row = wanted.get(event_index)
            if row is not None:
                assert seat == int(row["seat"]) and rnd.turn == seat
                key = action_key(event["cards"])
                probe = clone_for_probe(rnd)
                prod = production_ballot(probe, seat)
                v8 = human_v8_ballot(probe, seat)
                off_v8 = key not in v8
                if off_v8 == bool(row.get("human_action_appended")):
                    agree += 1
                else:
                    disagree += 1
                out.append({
                    "phase": "lead" if not rnd.trick.plays else "follow",
                    "rank": rnd.trump_rank, "mode": mode,
                    "contested": len(prod) > 1,
                    "off_ballot": key not in prod,
                    "off_human_v8_ballot": off_v8,
                    "role": actor_role(rnd, seat),
                    "player": row["player_id"],
                })
            rnd.play(seat, list(event["cards"]))
    expected = (manifest.get("stats") or {}).get("play_actions_off_ballot")
    off_v8 = sum(1 for d in out if d["off_human_v8_ballot"])
    summary = {
        "pointers": len(pointers),
        "resolved": len(out),
        "human_v8_off_ballot_recorded": expected,
        "human_v8_off_ballot_recomputed": off_v8,
        "human_v8_off_ballot_reproduced": (expected == off_v8),
        "per_decision_flag_agreements": agree,
        "per_decision_flag_disagreements": disagree,
        "human_v8_ballot": manifest.get("play_ballot"),
    }
    return out, summary


# ----------------------------------------------------------------- report

def build_report(registry: InputRegistry | None = None, *,
                 include_human: bool = True) -> dict:
    registry = registry or InputRegistry()
    report: dict = {
        "schema": "shengji-ballot-gap-report-v1",
        "production_ballot": "MCBot._candidates of mc-s0-report-lcb "
                             "(tractor-locked leads collapse to the heuristic pick)",
        "fraction_definition": "off_ballot / contested (ballot size > 1); "
                               "decisions counts every recorded decision",
        "bury_phase": "no teacher bury decisions exist in luna-rpc, Sol0 or "
                      "Luna0 (all recorded decisions are plays)",
    }
    luna = list(luna_rpc_decisions(registry))
    report["luna-rpc"] = aggregate(luna)
    for name, root in (("sol0", SOL0_ROOT), ("luna0", LUNA0_ROOT)):
        decisions = list(transcript_decisions(root, registry))
        agg = aggregate(decisions)
        agg["candidate_zero_chosen"] = sum(1 for d in decisions if d["candidate_zero"])
        agg["root"] = str(root)
        report[name] = agg
    if include_human:
        decisions, summary = human_decisions(registry)
        agg = aggregate(decisions)
        agg["human_v8"] = summary
        by_role: dict[str, dict] = defaultdict(_cell)
        for d in decisions:
            by_role[d["role"]]["decisions"] += 1
            if d["contested"]:
                by_role[d["role"]]["contested"] += 1
                by_role[d["role"]]["off_ballot"] += int(d["off_ballot"])
        agg["by_role"] = {k: _finish(v) for k, v in sorted(by_role.items())}
        report["human"] = agg
    report["inputs"] = registry.rows()
    return report


def write_report(out_dir: Path, report: dict) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "ballot_gap.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return path


def headline(report: dict) -> str:
    lines = []
    for name in ("luna-rpc", "sol0", "luna0", "human"):
        agg = report.get(name)
        if not agg:
            continue
        o = agg["overall"]
        frac = o["off_ballot_fraction"]
        frac_s = "n/a" if frac is None else f"{100 * frac:.1f}%"
        parts = [f"{name}: {o['off_ballot']}/{o['contested']} contested off-ballot "
                 f"({frac_s}; {o['decisions']} decisions)"]
        for phase in ("lead", "follow", "bury"):
            c = agg["by_phase"].get(phase)
            if c:
                f = c["off_ballot_fraction"]
                parts.append(f"{phase} {c['off_ballot']}/{c['contested']}"
                             + ("" if f is None else f" ({100 * f:.1f}%)"))
        lines.append("; ".join(parts))
        if name == "human":
            h = agg["human_v8"]
            lines.append(f"  human_v8 off-ballot (exhaustive-follows+throws-v1): "
                         f"recorded {h['human_v8_off_ballot_recorded']}, recomputed "
                         f"{h['human_v8_off_ballot_recomputed']}, reproduced="
                         f"{h['human_v8_off_ballot_reproduced']}")
    return "\n".join(lines)
