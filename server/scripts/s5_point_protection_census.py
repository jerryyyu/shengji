#!/usr/bin/env python3
"""Build the score-free S5 defensive point-protection replay census.

The motivating observation is narrow: a bot sometimes appears to discard a
5/10/K into a trick the other team wins even though a lower-point legal follow
may have existed.  Aggregate log counts cannot establish that claim.  This
script replays the exact frozen Fly snapshot and asks four structural questions
at each bot follow:

* was the current trick owned by an opponent;
* could any legal action by this seat win immediately;
* did the logged action carry more points than another legal action; and
* was a lower-point action present in the production ballot, root incumbent,
  rollout-policy choice, or preserved production decision record?

No belief world is sampled, no candidate is rolled out, no round score or
utility is read, and no treatment is implemented.  Published witnesses contain
only identifier-free digests and structural counters—not room names, player
names, source filenames, cards, hands, or raw decisions.  A positive census may
authorize design review for a later trigger-matched experiment; it cannot label
data, train, claim strength, promote, or deploy anything.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import live_champion_parent as LIVE_PARENT  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.ballot import mc_ballot  # noqa: E402
from shengji.engine.cards import total_points  # noqa: E402
from shengji.engine.legal import IllegalPlay, beats, validate_follow  # noqa: E402
from shengji.rl.replay_log import EXCLUDE_PLAYERS, group_rounds, rebuild_round  # noqa: E402


SCHEMA = "s5-point-protection-census-v1"
RUN_ID = "human-v8-s5-point-protection-census-v1"
CHAMPION = "mc-s0-report-lcb"
SOURCE_MANIFEST_SHA256 = (
    "07ff18fb35f2fb987f18b37b5100172e2751681fbfed17285ce7d7035232aa5e"
)
MAX_DISTINCT_FOLLOW_MULTISETS = 250_000
WITNESS_DOMAIN = b"shengji-s5-point-protection-witness-v1\0"
EXPERIMENTAL_FLAGS = (
    "SHENGJI_WEIGHTED_SPLITS",
    "SHENGJI_UNIFORM_DEAL",
    "SHENGJI_PHYSICAL_FILLS",
    "SHENGJI_ALLOW_BALLOT_MISMATCH",
)
SOURCE_PATHS = (
    "server/scripts/live_champion_parent.py",
    "server/scripts/s5_point_protection_census.py",
    "server/shengji/ai/heuristic.py",
    "server/shengji/ai/mcbot.py",
    "server/shengji/ai/memory.py",
    "server/shengji/ai/registry.py",
    "server/shengji/ai/smart.py",
    "server/shengji/engine/ballot.py",
    "server/shengji/engine/cards.py",
    "server/shengji/engine/combos.py",
    "server/shengji/engine/legal.py",
    "server/shengji/engine/round.py",
    "server/shengji/rl/replay_log.py",
)
FORBIDDEN_PUBLIC_KEYS = frozenset({
    "cards",
    "chosen",
    "filename",
    "hand",
    "hands",
    "human_action",
    "player",
    "player_name",
    "players",
    "room",
    "room_id",
    "source_filename",
    "source_name",
})


class CensusRefused(RuntimeError):
    """The score-free census or one of its immutable inputs drifted."""


class RowRefused(CensusRefused):
    """One replay row exceeded a declared structural boundary."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout.strip()


def producer_identity(*, smoke: bool) -> dict:
    git = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    if dirty and not smoke:
        raise CensusRefused("real census refuses a dirty tracked tree")
    return {
        "git": git,
        "tree_dirty": dirty,
        "script_sha256": sha256_file(SCRIPT),
        "promotable": not smoke,
    }


def action_key(action: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(str(card) for card in action))


def witness_digest(source_sha256: str, round_no: int,
                   event_index: int, seat: int) -> str:
    return sha256_bytes(WITNESS_DOMAIN + canonical_json([
        source_sha256, int(round_no), int(event_index), int(seat),
    ]))


def _is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    partial = Path(str(path) + ".partial")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path) or os.path.lexists(partial):
        raise CensusRefused(f"refusing to overwrite {path}")
    try:
        with partial.open("xb") as handle:
            handle.write(canonical_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(partial, path)
        partial.unlink()
    except BaseException:
        if partial.exists() and not path.exists():
            partial.unlink()
        raise
    if not _is_regular_unlinked(path):
        raise CensusRefused("published census is not regular/unlinked")


def _load_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise CensusRefused(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CensusRefused(f"JSON root is not an object: {path}")
    return value


def _evaluation_tagged(events: Iterable[Mapping[str, object]]) -> bool:
    for event in events:
        experiment = event.get("experiment")
        if event.get("training_excluded") is True:
            return True
        if isinstance(experiment, Mapping):
            if (experiment.get("training_excluded") is True
                    or experiment.get("schema") ==
                    "human-vs-bot-evaluation-v1"):
                return True
    return False


def source_population(manifest_path: Path, source_root: Path,
                      expected_sha256: str, *, smoke: bool
                      ) -> tuple[list[tuple[Path, str, int]], dict]:
    if not _is_regular_unlinked(manifest_path):
        raise CensusRefused("source manifest is missing/non-regular")
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest_lines = manifest_bytes.decode().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise CensusRefused("source manifest is unreadable") from exc
    actual_manifest_sha = sha256_bytes(manifest_bytes)
    if not is_sha256(expected_sha256):
        raise CensusRefused("expected source manifest SHA-256 is malformed")
    if actual_manifest_sha != expected_sha256:
        raise CensusRefused("source manifest SHA-256 drift")
    if not smoke and expected_sha256 != SOURCE_MANIFEST_SHA256:
        raise CensusRefused("real census requires the frozen Fly source manifest")
    members: list[tuple[Path, str, int]] = []
    seen: set[str] = set()
    for line_no, line in enumerate(manifest_lines, 1):
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or not is_sha256(fields[0]):
            raise CensusRefused(f"malformed source manifest line {line_no}")
        expected, raw_name = fields
        name = Path(raw_name.lstrip("* ")).name
        if not name.endswith(".jsonl") or name in seen:
            raise CensusRefused("source manifest member name/duplication drift")
        seen.add(name)
        path = (source_root / name).resolve()
        if path.parent != source_root.resolve() or not _is_regular_unlinked(path):
            raise CensusRefused("source member is missing/non-regular")
        size = path.stat().st_size
        if sha256_file(path) != expected:
            raise CensusRefused("source member differs from manifest")
        members.append((path, expected, size))
    if not members:
        raise CensusRefused("empty source manifest")
    members.sort(key=lambda item: item[0].name)
    # Hash only content identities and sizes. Room/source names stay private.
    commitment_rows = sorted([
        {"file_sha256": expected, "bytes": size}
        for _, expected, size in members
    ], key=lambda row: row["file_sha256"])
    return members, {
        "manifest_sha256": actual_manifest_sha,
        "member_count": len(members),
        "total_bytes": sum(size for _, _, size in members),
        "members_commitment_sha256": sha256_bytes(canonical_json(commitment_rows)),
        "source_names_published": False,
    }


def require_source_exact(path: Path, expected_sha256: str,
                         expected_size: int, phase: str) -> None:
    try:
        matches = (path.stat().st_size == expected_size
                   and sha256_file(path) == expected_sha256)
    except OSError as exc:
        raise CensusRefused(f"source member unavailable {phase}") from exc
    if not matches:
        raise CensusRefused(f"source member drifted {phase}")


def _multiset_actions(hand: Sequence[str], size: int,
                      limit: int) -> tuple[list[tuple[str, ...]], int]:
    if size <= 0 or size > len(hand):
        raise RowRefused("invalid follow size")
    items = sorted(Counter(hand).items())
    suffix = [0] * (len(items) + 1)
    for index in range(len(items) - 1, -1, -1):
        suffix[index] = suffix[index + 1] + items[index][1]
    leaves = 0
    out: list[tuple[str, ...]] = []

    def walk(index: int, remaining: int, chosen: list[str]) -> None:
        nonlocal leaves
        if remaining == 0:
            leaves += 1
            if leaves > limit:
                raise RowRefused("distinct follow multiset cap exceeded")
            out.append(tuple(chosen))
            return
        if index == len(items) or suffix[index] < remaining:
            return
        code, available = items[index]
        for count in range(min(available, remaining) + 1):
            chosen.extend([code] * count)
            walk(index + 1, remaining - count, chosen)
            if count:
                del chosen[-count:]

    walk(0, size, [])
    return out, leaves


def legal_follow_actions(rnd, seat: int,
                         *, limit: int = MAX_DISTINCT_FOLLOW_MULTISETS) -> tuple[list[tuple[str, ...]], int]:
    if rnd.trick is None or not rnd.trick.plays or rnd.ordering is None:
        raise RowRefused("row is not a follow decision")
    lead = list(rnd.trick.plays[0].cards)
    multisets, examined = _multiset_actions(rnd.hands[seat], len(lead), limit)
    legal: list[tuple[str, ...]] = []
    for action in multisets:
        try:
            validate_follow(list(action), rnd.hands[seat], lead, rnd.ordering)
        except IllegalPlay:
            continue
        legal.append(action)
    legal = sorted(set(legal))
    if not legal:
        raise RowRefused("no legal follow action enumerated")
    return legal, examined


def _current_policy_geometry(rnd, seat: int, production_bot,
                             legal: set[tuple[str, ...]]) -> dict:
    before = canonical_json({
        "hands": rnd.hands,
        "history": [[{"seat": play.seat, "cards": play.cards}
                     for play in trick.plays] for trick in rnd.history],
        "open": ([{"seat": play.seat, "cards": play.cards}
                  for play in rnd.trick.plays] if rnd.trick else None),
    })
    candidates = [action_key(action) for action in production_bot._candidates(
        copy.deepcopy(rnd), seat)]
    if not candidates or len(candidates) != len(set(candidates)):
        raise RowRefused("production ballot is empty/duplicated")
    if any(candidate not in legal for candidate in candidates):
        raise RowRefused("production ballot contains an illegal follow")
    rollout = action_key(production_bot.rollout_policy.decide_play(
        copy.deepcopy(rnd), seat))
    if rollout not in legal:
        raise RowRefused("rollout policy produced an illegal follow")
    after = canonical_json({
        "hands": rnd.hands,
        "history": [[{"seat": play.seat, "cards": play.cards}
                     for play in trick.plays] for trick in rnd.history],
        "open": ([{"seat": play.seat, "cards": play.cards}
                  for play in rnd.trick.plays] if rnd.trick else None),
    })
    if before != after:
        raise RowRefused("score-free policy geometry mutated replay state")
    return {"candidates": candidates, "candidate0": candidates[0],
            "rollout": rollout}


def ballot_identity(production_bot) -> dict:
    ballot = mc_ballot(production_bot)
    return {
        "name": ballot.name,
        "version": ballot.version,
        "source": ballot.source,
        "config": [list(item) for item in ballot.config],
        "source_digest": ballot.source_digest,
        "digest": ballot.digest,
    }


def _action_population(value: object) -> list[tuple[str, ...]] | None:
    if (not isinstance(value, list) or not value
            or any(not isinstance(action, list) or not action
                   or any(not isinstance(card, str) for card in action)
                   for action in value)):
        return None
    return [action_key(action) for action in value]


def _logged_decision(event: Mapping[str, object], historical: tuple[str, ...],
                     legal: set[tuple[str, ...]], production_bot,
                     current_candidates: list[tuple[str, ...]]) -> dict:
    decision = event.get("decision")
    if not isinstance(decision, Mapping):
        return {"present": False, "valid": False, "problems": ["absent"],
                "candidates": [], "work_complete": False}
    problems: list[str] = []
    if decision.get("schema") != "mc-decision-v2":
        problems.append("schema")
    if decision.get("policy") != CHAMPION:
        problems.append("policy")
    if decision.get("policy_class") != type(production_bot).__name__:
        problems.append("policy_class")
    code = decision.get("code")
    if (not isinstance(code, Mapping)
            or code.get("mcbot_sha256") != sha256_file(
                SERVER / "shengji/ai/mcbot.py")):
        problems.append("mcbot_source")
    expected_ballot = ballot_identity(production_bot)
    logged_ballot = decision.get("ballot")
    if not isinstance(logged_ballot, Mapping):
        problems.append("ballot_identity")
    elif any(logged_ballot.get(key) != value
             for key, value in expected_ballot.items()):
        problems.append("ballot_identity")
    candidates = _action_population(decision.get("candidates"))
    if candidates is None:
        candidates = []
        problems.append("candidates")
    if not candidates or len(candidates) != len(set(candidates)):
        problems.append("candidate_population")
    if any(candidate not in legal for candidate in candidates):
        problems.append("candidate_legality")
    if candidates != current_candidates:
        problems.append("candidate_replay")
    try:
        raw_played_index = decision["played_index"]
        if isinstance(raw_played_index, bool):
            raise TypeError
        played_index = int(raw_played_index)
        raw_played = decision["played"]
        if (not isinstance(raw_played, list) or not raw_played
                or any(not isinstance(card, str) for card in raw_played)):
            raise TypeError
        played = action_key(raw_played)
    except (KeyError, TypeError, ValueError):
        played_index, played = -1, ()
        problems.append("played")
    if (played != historical or played_index < 0
            or played_index >= len(candidates)
            or (candidates and candidates[played_index] != historical)):
        problems.append("played_binding")
    work = decision.get("work")
    work_complete = isinstance(work, Mapping) and work.get("complete") is True
    if not work_complete:
        problems.append("work_incomplete")
    if not isinstance(decision.get("reason"), str):
        problems.append("reason")
    return {
        "present": True,
        "valid": not problems,
        "problems": sorted(set(problems)),
        "candidates": candidates,
        "work_complete": work_complete,
    }


def analyze_bot_follow(rnd, seat: int, cards: Sequence[str],
                       event: Mapping[str, object], *, source_sha256: str,
                       round_no: int, event_index: int, production_bot) -> dict:
    if rnd.ordering is None or rnd.trick is None or not rnd.trick.plays:
        raise RowRefused("not a replayable follow")
    historical = action_key(cards)
    legal_list, examined = legal_follow_actions(rnd, seat)
    legal = set(legal_list)
    if historical not in legal:
        raise RowRefused("historical follow absent from legal universe")
    winner, incumbent_suit, incumbent_top = production_bot._current_winner(rnd)
    lead = list(rnd.trick.plays[0].cards)
    legal_winners = [action for action in legal_list if beats(
        list(action), lead, incumbent_suit, incumbent_top, rnd.ordering)[0]]
    historical_wins = beats(
        list(historical), lead, incumbent_suit, incumbent_top,
        rnd.ordering)[0]
    legal_points = {action: total_points(action) for action in legal_list}
    historical_points = legal_points[historical]
    minimum_points = min(legal_points.values())
    lower = [action for action, value in legal_points.items()
             if value < historical_points]
    minimum = [action for action, value in legal_points.items()
               if value == minimum_points]
    current = _current_policy_geometry(rnd, seat, production_bot, legal)
    logged = _logged_decision(
        event, historical, legal, production_bot, current["candidates"])
    current_points = {action: legal_points[action]
                      for action in current["candidates"]}
    logged_points = {action: legal_points[action]
                     for action in logged["candidates"] if action in legal_points}
    return {
        "witness_sha256": witness_digest(
            source_sha256, round_no, event_index, seat),
        "role": "attacker" if rnd.is_attacker(seat) else "defender",
        "follow_position": len(rnd.trick.plays) + 1,
        "lead_size": len(lead),
        "cards_remaining_total": sum(len(hand) for hand in rnd.hands),
        "incumbent_is_opponent": winner % 2 != seat % 2,
        "historical_wins_immediately": historical_wins,
        "legal_action_count": len(legal_list),
        "distinct_multisets_examined": examined,
        "legal_winner_count": len(legal_winners),
        "historical_points": historical_points,
        "minimum_legal_points": minimum_points,
        "avoidable_point_delta": historical_points - minimum_points,
        "lower_point_legal_count": len(lower),
        "minimum_action_count": len(minimum),
        "minimum_action_on_current_ballot": any(
            action in current_points for action in minimum),
        "lower_point_on_current_ballot": any(
            current_points[action] < historical_points for action in current_points),
        "current_ballot_count": len(current["candidates"]),
        "current_candidate0_matches_historical":
            current["candidate0"] == historical,
        "current_candidate0_points": legal_points[current["candidate0"]],
        "rollout_policy_matches_historical": current["rollout"] == historical,
        "rollout_policy_points": legal_points[current["rollout"]],
        "logged_decision_present": logged["present"],
        "logged_decision_valid": logged["valid"],
        "logged_decision_problem_codes": logged["problems"],
        "logged_decision_work_complete": logged["work_complete"],
        "logged_candidate_count": len(logged["candidates"]),
        "lower_point_on_logged_ballot": any(
            value < historical_points for value in logged_points.values()),
        # Filled only after the fourth logged play structurally resolves this
        # trick. It is hindsight DEV classification, never a policy label.
        "final_winner_is_opponent": None,
        "structural_trigger": False,
        "reproduced_by_current_policy_surface": False,
        "classification": None,
    }


def _finalize_row(row: dict, final_winner: int, seat: int) -> dict:
    row = dict(row)
    final_enemy = final_winner % 2 != seat % 2
    row["final_winner_is_opponent"] = final_enemy
    trigger = bool(
        row["incumbent_is_opponent"]
        and not row["historical_wins_immediately"]
        and row["legal_winner_count"] == 0
        and row["historical_points"] > 0
        and row["avoidable_point_delta"] > 0
        and final_enemy
    )
    row["structural_trigger"] = trigger
    if not trigger:
        return row
    current_sourcing_gap = not row["lower_point_on_current_ballot"]
    row["reproduced_by_current_policy_surface"] = bool(
        row["logged_decision_valid"]
        or current_sourcing_gap
        or row["current_candidate0_matches_historical"]
        or row["rollout_policy_matches_historical"]
    )
    if row["logged_decision_valid"]:
        if row["lower_point_on_logged_ballot"]:
            row["classification"] = (
                "logged_champion_ranked_or_fell_back_over_lower_point")
        else:
            row["classification"] = "logged_champion_ballot_sourcing_gap"
    elif row["lower_point_on_current_ballot"]:
        row["classification"] = "historical_identity_unknown_current_ballot_has_lower"
    else:
        row["classification"] = "current_ballot_sourcing_gap"
    return row


def _counter_add(target: Counter[str], source: Counter[str]) -> None:
    for key, value in source.items():
        target[key] += value


def _record_rejection(examples: dict[str, list[str]], reason: str,
                      digest: str) -> None:
    bucket = examples.setdefault(reason, [])
    if len(bucket) < 3:
        bucket.append(digest)


def census_sources(members: list[tuple[Path, str, int]],
                   production_bot) -> tuple[Counter[str], dict, list[dict]]:
    totals: Counter[str] = Counter()
    rejection_examples: dict[str, list[str]] = {}
    witnesses: list[dict] = []
    for source_path, source_sha, source_size in members:
        totals["source_files_seen"] += 1
        require_source_exact(
            source_path, source_sha, source_size, "before replay")
        try:
            rounds = group_rounds(str(source_path))
        except Exception as exc:
            raise CensusRefused(
                f"source JSONL cannot be grouped: {type(exc).__name__}") from exc
        require_source_exact(
            source_path, source_sha, source_size, "during replay read")
        for round_no, events in sorted(rounds.items()):
            totals["rounds_seen"] += 1
            round_ref = witness_digest(source_sha, round_no, -1, -1)
            if _evaluation_tagged(events):
                raise CensusRefused("evaluation-only round entered source snapshot")
            start = next((event for event in events
                          if event.get("e") == "round_start"), None)
            end = next((event for event in events
                        if event.get("e") == "round_end"), None)
            if start is None or end is None:
                totals["rounds_rejected_incomplete"] += 1
                _record_rejection(
                    rejection_examples, "round_incomplete", round_ref)
                continue
            players = start.get("players")
            if (not isinstance(players, list) or len(players) != 4
                    or any(not isinstance(player, Mapping) for player in players)):
                totals["rounds_rejected_player_population"] += 1
                _record_rejection(
                    rejection_examples, "round_player_population", round_ref)
                continue
            if any(str(player.get("name")) in EXCLUDE_PLAYERS
                   for player in players):
                totals["rounds_excluded_test_player"] += 1
                continue
            try:
                rnd = rebuild_round(events)
            except Exception as exc:
                totals[f"rounds_rejected_setup_{type(exc).__name__}"] += 1
                _record_rejection(
                    rejection_examples, "round_setup_replay", round_ref)
                continue
            if rnd is None:
                totals["rounds_rejected_missing_setup"] += 1
                _record_rejection(
                    rejection_examples, "round_missing_setup", round_ref)
                continue

            local: Counter[str] = Counter()
            pending: list[tuple[int, dict]] = []
            completed_rows: list[dict] = []
            replay_error: BaseException | None = None
            for event_index, event in enumerate(events):
                if event.get("e") != "play":
                    continue
                if rnd.phase != "play":
                    replay_error = CensusRefused("play event outside play phase")
                    break
                seat, cards = event.get("seat"), event.get("cards")
                if (isinstance(seat, bool) or not isinstance(seat, int)
                        or seat != rnd.turn or not isinstance(cards, list)):
                    replay_error = CensusRefused("logged play shape/turn drift")
                    break
                if event.get("bot") is True:
                    local["bot_play_events"] += 1
                    if rnd.trick is not None and rnd.trick.plays:
                        local["bot_follow_events"] += 1
                        try:
                            row = analyze_bot_follow(
                                rnd, seat, cards, event,
                                source_sha256=source_sha,
                                round_no=round_no, event_index=event_index,
                                production_bot=production_bot)
                        except RowRefused as exc:
                            reason = str(exc).replace(" ", "_")
                            local[f"bot_follow_rows_refused_{reason}"] += 1
                        else:
                            local["bot_follow_rows_analyzed"] += 1
                            if row["incumbent_is_opponent"]:
                                local["bot_follow_opponent_incumbent"] += 1
                            if row["legal_winner_count"] == 0:
                                local["bot_follow_no_legal_winner"] += 1
                            if row["avoidable_point_delta"] > 0:
                                local["bot_follow_lower_point_legal"] += 1
                            if row["logged_decision_present"]:
                                local["bot_follow_logged_decision_present"] += 1
                            if row["logged_decision_valid"]:
                                local["bot_follow_logged_decision_valid"] += 1
                            for problem in row["logged_decision_problem_codes"]:
                                local[f"logged_decision_problem_{problem}"] += 1
                            pending.append((seat, row))
                previous_last = rnd.last_trick
                try:
                    rnd.play(seat, cards)
                except Exception as exc:
                    replay_error = exc
                    break
                if rnd.last_trick is not previous_last:
                    if rnd.last_trick is None or rnd.last_trick.winner is None:
                        replay_error = CensusRefused("closed trick lacks winner")
                        break
                    for pending_seat, row in pending:
                        completed_rows.append(_finalize_row(
                            row, rnd.last_trick.winner, pending_seat))
                    pending.clear()

            if replay_error is not None or rnd.phase != "round_end" or pending:
                reason = (type(replay_error).__name__ if replay_error is not None
                          else "incomplete_replay")
                totals[f"rounds_rejected_play_{reason}"] += 1
                _record_rejection(
                    rejection_examples, "round_play_replay", round_ref)
                continue
            totals["rounds_replayed_complete"] += 1
            _counter_add(totals, local)
            for row in completed_rows:
                if not row["structural_trigger"]:
                    continue
                totals["structural_triggers"] += 1
                totals[f"trigger_role_{row['role']}"] += 1
                totals[f"trigger_follow_position_{row['follow_position']}"] += 1
                totals[f"trigger_lead_size_{row['lead_size']}"] += 1
                totals[f"trigger_class_{row['classification']}"] += 1
                if row["logged_decision_valid"]:
                    totals["trigger_logged_champion_valid"] += 1
                if row["lower_point_on_current_ballot"]:
                    totals["trigger_current_ballot_has_lower"] += 1
                if row["current_candidate0_matches_historical"]:
                    totals["trigger_current_candidate0_matches_historical"] += 1
                if row["rollout_policy_points"] < row["historical_points"]:
                    totals["trigger_rollout_policy_uses_lower"] += 1
                if row["rollout_policy_matches_historical"]:
                    totals["trigger_rollout_policy_matches_historical"] += 1
                if row["reproduced_by_current_policy_surface"]:
                    totals["structural_triggers_reproduced"] += 1
                witnesses.append(row)
    witnesses.sort(key=lambda row: row["witness_sha256"])
    if len({row["witness_sha256"] for row in witnesses}) != len(witnesses):
        raise CensusRefused("duplicate public witness digest")
    return totals, dict(sorted(rejection_examples.items())), witnesses


def _material_identity() -> dict:
    files = [{"path": path, "sha256": sha256_file(REPO / path)}
             for path in SOURCE_PATHS]
    return {
        "files": files,
        "sha256": sha256_bytes(canonical_json(files)),
    }


def _runtime(*, smoke: bool) -> tuple[dict, object]:
    enabled = [name for name in EXPERIMENTAL_FLAGS if os.environ.get(name)]
    if enabled:
        raise CensusRefused(
            f"experimental sampler/ballot flags must be unset: {enabled}")
    from shengji.engine import combos, fast
    if smoke:
        parent = LIVE_PARENT.expected_parent()
    else:
        if (os.environ.get("SHENGJI_FAST") != "1"
                or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"):
            raise CensusRefused(
                "set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")
        if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
            raise CensusRefused("compiled engine requested but not active")
        parent = LIVE_PARENT.require_portable_live_champion_parent()
    bot = make_bot(CHAMPION, seed=0)
    if type(bot.rollout_policy).__name__ != "HeuristicBot":
        raise CensusRefused("live champion rollout policy drift")
    runtime = {
        "fast_engine": bool(fast.HAVE_FAST),
        "compiled_fast_binary_sha256": (
            sha256_file(fast._fast.__file__) if fast.HAVE_FAST else None),
        "production_ballot": ballot_identity(bot),
        "rollout_policy_class": type(bot.rollout_policy).__name__,
    }
    return {"identity": runtime, "live_parent": parent}, bot


def build_census(manifest_path: Path, source_root: Path,
                 expected_manifest_sha256: str, *, smoke: bool = False,
                 production_bot=None, runtime_payload: dict | None = None) -> dict:
    producer = producer_identity(smoke=smoke)
    members, source = source_population(
        manifest_path.resolve(), source_root.resolve(),
        expected_manifest_sha256, smoke=smoke)
    if runtime_payload is None:
        runtime_payload, default_bot = _runtime(smoke=smoke)
    else:
        default_bot = make_bot(CHAMPION, seed=0)
    bot = production_bot or default_bot
    totals, rejection_examples, witnesses = census_sources(members, bot)
    if totals["rounds_replayed_complete"] <= 0:
        raise CensusRefused("no complete round replayed")
    if totals["bot_follow_rows_analyzed"] <= 0:
        raise CensusRefused("no bot follow row analyzed")
    witness_set_sha = sha256_bytes(canonical_json(witnesses))
    reproduced = totals.get("structural_triggers_reproduced", 0)
    if not witnesses:
        next_gate = "CLOSE_S5_NO_STRUCTURAL_TRIGGER"
    elif reproduced:
        next_gate = "S5_DESIGN_REVIEW_ELIGIBLE"
    else:
        next_gate = "CLOSE_S5_NOT_REPRODUCED_BY_CURRENT_SURFACE"
    packet = {
        "schema": SCHEMA,
        "run_id": RUN_ID,
        "producer": producer,
        "material": _material_identity(),
        "runtime": runtime_payload,
        "source": source,
        "contract": {
            "population": "all complete non-test rounds in frozen Fly snapshot",
            "actor": "event.bot is exactly true at a follow decision",
            "trigger": (
                "opponent owns incumbent; actor has no legal immediate winner; "
                "logged losing action carries points; a lower-point legal follow "
                "exists; actual trick later resolves to opponent team"
            ),
            "legal_universe": "all distinct-code legal follow multisets",
            "max_distinct_follow_multisets": MAX_DISTINCT_FOLLOW_MULTISETS,
            "current_policy_checks": [
                "production root ballot", "root candidate zero",
                "HeuristicBot rollout-policy choice",
                "preserved mc-decision-v2 record when present",
            ],
            "historical_hindsight_is_dev_only": True,
            "formal_followup_population": "fresh trigger-matched bot states",
        },
        "stats": dict(sorted(totals.items())),
        "rejection_examples": rejection_examples,
        "witnesses": witnesses,
        "witness_set_sha256": witness_set_sha,
        "decision": next_gate,
        "authority": {
            "score_free": True,
            "round_scores_read": False,
            "belief_worlds_sampled": 0,
            "candidate_rollouts": 0,
            "full_champion_mc_replays": 0,
            "raw_cards_published": False,
            "room_or_player_identifiers_published": False,
            "human_log_witnesses_are_dev_only": True,
            "treatment_implemented": False,
            "strength_run_authorized": False,
            "labels_authorized": False,
            "training_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    packet["packet_sha256"] = sha256_bytes(canonical_json(packet))
    return packet


def forbidden_public_paths(value: object,
                           path: tuple[str, ...] = ()) -> list[str]:
    problems: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = (*path, key)
            if key.lower() in FORBIDDEN_PUBLIC_KEYS:
                problems.append(".".join(child_path))
            problems.extend(forbidden_public_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            problems.extend(forbidden_public_paths(
                child, (*path, str(index))))
    return problems


def packet_problems(actual: dict, expected: dict) -> list[str]:
    problems = []
    if actual != expected:
        problems.append("full census recomputation drift")
    authority = actual.get("authority", {})
    if (authority.get("score_free") is not True
            or authority.get("round_scores_read") is not False
            or authority.get("belief_worlds_sampled") != 0
            or authority.get("candidate_rollouts") != 0
            or authority.get("full_champion_mc_replays") != 0
            or authority.get("labels_authorized") is not False
            or authority.get("training_authorized") is not False
            or authority.get("strength_claim") is not False):
        problems.append("score-free authority drift")
    if forbidden_public_paths(actual):
        problems.append("private/raw field leaked into census")
    return sorted(set(problems))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for command in ("freeze", "verify"):
        child = commands.add_parser(command)
        child.add_argument("--source-manifest", required=True)
        child.add_argument("--source-root", required=True)
        child.add_argument("--expected-source-manifest-sha256", required=True)
        child.add_argument("--out", required=True)
        child.add_argument("--expected-git")
        child.add_argument("--smoke", action="store_true")
        if command == "verify":
            child.add_argument("--expected-packet-sha256")
    return root


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if not args.smoke and not args.expected_git:
        raise CensusRefused("real census requires --expected-git")
    if (args.command == "verify" and not args.smoke
            and not args.expected_packet_sha256):
        raise CensusRefused(
            "real verification requires --expected-packet-sha256")
    if args.expected_git and _git("rev-parse", "HEAD") != args.expected_git:
        raise CensusRefused("producer Git differs from expected Git")
    expected = build_census(
        Path(args.source_manifest), Path(args.source_root),
        args.expected_source_manifest_sha256, smoke=args.smoke)
    out = Path(args.out).resolve()
    if args.command == "freeze":
        publish_exclusive(out, expected)
        print(json.dumps({
            "status": "S5_SCORE_FREE_CENSUS_FROZEN",
            "path": str(out),
            "sha256": sha256_file(out),
            "structural_triggers": expected["stats"].get(
                "structural_triggers", 0),
            "worlds_sampled": 0,
            "candidate_rollouts": 0,
            "next_gate": expected["decision"],
        }, sort_keys=True))
        return
    if not _is_regular_unlinked(out):
        raise CensusRefused("census output is missing/non-regular")
    if (args.expected_packet_sha256
            and sha256_file(out) != args.expected_packet_sha256):
        raise CensusRefused("external census SHA-256 drift")
    actual = _load_object(out)
    problems = packet_problems(actual, expected)
    if problems:
        raise CensusRefused("; ".join(problems))
    print(json.dumps({
        "status": "S5_SCORE_FREE_CENSUS_VERIFIED",
        "path": str(out),
        "sha256": sha256_file(out),
        "structural_triggers": actual["stats"].get("structural_triggers", 0),
        "worlds_sampled": 0,
        "candidate_rollouts": 0,
        "next_gate": actual["decision"],
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except CensusRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
