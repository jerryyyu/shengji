"""Extractor: Luna turn-RPC self-play trajectories.

Source: ``~/.shengji-runs/pt-luna-rpc-*-private/attempts/*/trajectory.json``
(schema ``privileged-teacher-luna-selfplay-private-trajectory-v1``) with the
sibling ``terminal.json`` (completion, final_attacker_points,
signed_level_utility for seat 0), ``attempt.json`` (authority labels) and
``manifest.json`` (file sha256s).  Only attempts whose terminal receipt says
``completion: true`` count (62 games / 4,808 afterstates).

Format facts this extractor relies on (verified against the data)
------------------------------------------------------------------
* every event is one play in the play phase; ``state_after[i] ==
  state_before[i+1]`` (no unrecorded plays), the last ``state_after`` is
  ``{"phase": "round_end", "terminal_redacted": true}``;
* ``legal_ballot`` is the WIDE search ballot the agent chose from (not the
  exhaustive legal set) and ``production_prior`` is the production
  ``MCBot._candidates`` ballot — mapped to ``ballot`` / ``production_ballot``;
  the exhaustive set comes from ``harvest.legal``;
* single-candidate events were advanced without consulting the model
  (``_advance_forced``): ``policy = "forced:single-candidate"``;
* the trajectory records hands, not a deal order.  A synthetic deck that
  reproduces the hands is built (``rebuild.synthetic_deck``) and, being
  hidden-hand data, lives only in the private split (``state_private``);
  the burial (``hidden_burial``) is withheld from public rows for the same
  reason (``setup.buried = null`` there).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from ..engine.round import Round
from .common import (LUNA_ROOTS, ExtractResult, InputRegistry, action_key,
                     sha256_bytes, trump_mode)
from .legal import enumerate_legal
from .rebuild import (RebuildError, actor_role, hands_snapshot, outcome_for,
                      round_from_setup, signed_level_utility, synthetic_deck)
from .schema import finalize_record, split_record

POLICY = "gpt-5.6-luna"          # spec's policy id for the Luna teacher
FORCED_POLICY = "forced:single-candidate"
TRAJECTORY_SCHEMA = "privileged-teacher-luna-selfplay-private-trajectory-v1"
TERMINAL_SCHEMA = "privileged-teacher-luna-selfplay-terminal-receipt-v1"


class LunaFormatError(ValueError):
    pass


@dataclass
class LunaGame:
    root: Path
    attempt: Path
    trajectory: dict
    terminal: dict
    attempt_meta: dict
    manifest: dict

    @property
    def ref(self) -> str:
        return f"{self.root.name}/attempts/{self.attempt.name}"

    @property
    def events(self) -> list[dict]:
        return self.trajectory["events"]


def iter_games(roots: Sequence[Path] = LUNA_ROOTS,
               registry: InputRegistry | None = None) -> Iterator[LunaGame]:
    """Complete games only, in root order then attempt-directory order."""
    registry = registry or InputRegistry()
    for root in roots:
        attempts_dir = Path(root) / "attempts"
        if not attempts_dir.is_dir():
            raise LunaFormatError(f"missing attempts directory: {attempts_dir}")
        for attempt in sorted(p for p in attempts_dir.iterdir() if p.is_dir()):
            terminal_path = attempt / "terminal.json"
            if not terminal_path.is_file():
                continue                      # failed attempt: no receipt
            terminal = registry.read_json(terminal_path)
            if terminal.get("completion") is not True:
                continue
            trajectory_bytes = registry.read_bytes(attempt / "trajectory.json")
            attempt_bytes = registry.read_bytes(attempt / "attempt.json")
            manifest = registry.read_json(attempt / "manifest.json")
            files = manifest.get("files", {})
            for name, data in (("trajectory.json", trajectory_bytes),
                               ("attempt.json", attempt_bytes)):
                if files.get(name) != sha256_bytes(data):
                    raise LunaFormatError(f"{attempt}/{name}: manifest sha256 drift")
            trajectory = json.loads(trajectory_bytes)
            if trajectory.get("schema") != TRAJECTORY_SCHEMA:
                raise LunaFormatError(f"{attempt}: trajectory schema drift")
            if terminal.get("schema") != TERMINAL_SCHEMA:
                raise LunaFormatError(f"{attempt}: terminal schema drift")
            if terminal.get("trajectory_sha256") != files.get("trajectory.json"):
                raise LunaFormatError(f"{attempt}: terminal/trajectory binding drift")
            yield LunaGame(Path(root), attempt, trajectory, terminal,
                           json.loads(attempt_bytes), manifest)


def _check_state(rnd: Round, snapshot: dict, where: str) -> None:
    if [sorted(h) for h in rnd.hands] != [sorted(h) for h in snapshot["hands_by_seat"]]:
        raise RebuildError(f"{where}: hands drift")
    if rnd.turn != snapshot["turn"] or rnd.attacker_points != snapshot["attacker_points"]:
        raise RebuildError(f"{where}: turn/points drift")
    trick = snapshot["current_trick"]
    plays = [] if rnd.trick is None else [
        {"cards": list(p.cards), "seat": p.seat} for p in rnd.trick.plays]
    if plays != [{"cards": list(p["cards"]), "seat": p["seat"]}
                 for p in trick["plays"]]:
        raise RebuildError(f"{where}: current trick drift")
    if len(rnd.history) != len(snapshot["history"]):
        raise RebuildError(f"{where}: history length drift")
    if sorted(rnd.buried) != sorted(snapshot["hidden_burial"]):
        raise RebuildError(f"{where}: burial drift")


def game_setup(game: LunaGame) -> tuple[list[str], dict]:
    """Synthetic deck + setup for one game, from the first state_before."""
    sb0 = game.events[0]["state_before"]
    if sb0["phase"] != "play" or sb0["history"] or sb0["current_trick"]["plays"]:
        raise LunaFormatError(f"{game.ref}: first event is not the opening lead")
    declaration = sb0["declaration"]
    deck = synthetic_deck(sb0["hands_by_seat"], sb0["hidden_burial"],
                          banker=sb0["banker"], declaration=declaration,
                          trump_suit=sb0["trump_suit"],
                          trump_is_nt=sb0["trump_is_nt"])
    setup = {
        "trump_rank": sb0["trump_rank"],
        "banker": sb0["banker"],
        "declarations": ([] if declaration is None else
                         [{"seat": declaration["seat"],
                           "cards": list(declaration["cards"])}]),
        "declaration": None if declaration is None else dict(declaration),
        "trump_suit": sb0["trump_suit"],
        "trump_is_nt": bool(sb0["trump_is_nt"]),
        "buried": sorted(sb0["hidden_burial"]),
    }
    return deck, setup


def extract_luna(roots: Sequence[Path] = LUNA_ROOTS, *, cap: int | None = 256,
                 registry: InputRegistry | None = None,
                 limit: int | None = None) -> ExtractResult:
    registry = registry or InputRegistry()
    result = ExtractResult("luna-rpc")
    games = decisions = forced = failed_throws = 0
    for game in iter_games(roots, registry):
        if limit is not None and games >= limit:
            break
        games += 1
        deck, setup = game_setup(game)
        rnd = round_from_setup(deck, setup)
        terminal = game.terminal
        banker = setup["banker"]
        final_points = int(terminal["final_attacker_points"])
        if terminal["signed_level_utility"] != signed_level_utility(
                final_points, banker_seat=banker, perspective_seat=0):
            raise LunaFormatError(f"{game.ref}: terminal utility convention drift")
        authority = dict(game.attempt_meta.get("authority") or {})
        prefix: list[dict] = []
        for event in game.events:
            index = event["index"]
            if index != len(prefix):
                raise LunaFormatError(f"{game.ref}: event index gap at {index}")
            seat = event["seat"]
            _check_state(rnd, event["state_before"], f"{game.ref}#event-{index}")
            if rnd.turn != seat or rnd.phase != "play":
                raise RebuildError(f"{game.ref}#event-{index}: not seat's turn")
            action = list(event["action"])
            ballot = [list(a) for a in event["legal_ballot"]]
            prior = [list(a) for a in event["production_prior"]]
            ci = event["candidate_index"]
            if action_key(ballot[ci]) != action_key(action):
                raise LunaFormatError(f"{game.ref}#event-{index}: candidate_index drift")
            legal = enumerate_legal(rnd, seat, cap=cap,
                                    must_include=ballot + [action])
            hidden = hands_snapshot(rnd)
            record = finalize_record({
                "source": "luna-rpc",
                "source_ref": f"{game.ref}/trajectory.json#event-{index}",
                "policy": POLICY if len(ballot) > 1 else FORCED_POLICY,
                "deck": deck,
                "setup": setup,
                "plays_prefix": [dict(p) for p in prefix],
                "seat": seat,
                "ply": len(prefix),
                "trick": len(prefix) // 4,
                "role": actor_role(rnd, seat),
                "legal_actions": legal.actions,
                "legal_actions_complete": legal.complete,
                "legal_actions_count": legal.count,
                "ballot": ballot,
                "production_ballot": prior,
                "allocation": None,
                "action_values": None,
                "action": action,
                "outcome": outcome_for(final_points, banker=banker, seat=seat),
                "authority": authority or None,
                "hidden_hands": hidden,
            })
            if len(ballot) <= 1:
                forced += 1
            prev_last = rnd.last_trick
            rnd.play(seat, action)
            played = _engine_play(rnd, seat, prev_last)
            if action_key(played) != action_key(action):
                failed_throws += 1
                record = finalize_record({**record, "engine_play": played})
            prefix.append({"seat": seat, "cards": played})
            # the deal order AND the burial are hidden-world data: public
            # rows carry neither (state_private); the private twin has both
            public, private = split_record(
                record, private_fields=("deck", "setup.buried"))
            result.add(public, private)
            decisions += 1
        if rnd.phase != "round_end" or rnd.attacker_points != final_points:
            raise RebuildError(f"{game.ref}: replay did not reach the receipt outcome")
        if terminal.get("mirror") != game.trajectory.get("mirror"):
            raise LunaFormatError(f"{game.ref}: mirror drift")
    result.counts = {"games": games, "rounds": games, "decisions": decisions,
                     "forced_single_candidate": forced,
                     "failed_throws": failed_throws,
                     "private_records": len(result.private)}
    result.inputs = registry.rows()
    result.notes.append("policy id 'gpt-5.6-luna' is the spec's label; the "
                        "artifact carries only model_process_id hashes")
    result.notes.append("deck is synthetic (hands recorded, deal order not) "
                        "and lives only in the private split")
    return result


def _engine_play(rnd: Round, seat: int, prev_last) -> list[str]:
    if rnd.trick is not None and rnd.trick.plays:
        for p in reversed(rnd.trick.plays):
            if p.seat == seat:
                return list(p.cards)
    if rnd.last_trick is not None and rnd.last_trick is not prev_last:
        for p in rnd.last_trick.plays:
            if p.seat == seat:
                return list(p.cards)
    raise RebuildError("engine play not found")


def iter_decisions_for_gap(roots: Sequence[Path] = LUNA_ROOTS,
                           registry: InputRegistry | None = None) -> Iterator[dict]:
    """Lightweight view for the ballot-gap report (no replay needed)."""
    for game in iter_games(roots, registry):
        sb0 = game.events[0]["state_before"]
        for event in game.events:
            sb = event["state_before"]
            yield {
                "ref": game.ref,
                "index": event["index"],
                "phase": "lead" if not sb["current_trick"]["plays"] else "follow",
                "rank": sb0["trump_rank"],
                "mode": trump_mode(sb0["trump_suit"], sb0["trump_is_nt"]),
                "contested": len(event["legal_ballot"]) > 1,
                "action": action_key(event["action"]),
                "production_ballot": {action_key(a) for a in event["production_prior"]},
                "ballot": {action_key(a) for a in event["legal_ballot"]},
            }
