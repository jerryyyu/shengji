#!/usr/bin/env python3
"""Capture a reusable, score-free population where the lead ballot drops a pair.

The million-round census established that pair omission is real but very
concentrated in early leads.  This producer turns that diagnosis into an
evaluation asset without computing any game outcome:

* every deal is assigned to DEV, CALIB, or REPORT before play;
* all lead decisions use the complete production SmartBot round setup,
  including the post-deal declaration grace pass;
* at most one affected state per (deal, phase band) is retained;
* parallel shards partition one ascending seed stream exactly; and
* merge takes the globally earliest rows in each split/band cell.

Mid/late states are intentionally over-sampled for diagnosis.  A later screen
must use the full capture stream's search-reachable omission weights for its
primary aggregate; it may not treat the balanced row quotas as natural
frequencies.  The stream counters include every omission even though at most
one replay row per (deal, phase band) is retained.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from shengji.ai.registry import make_bot
from shengji.engine.cards import SUITS, TRUMP
from shengji.engine.combos import decompose
from shengji.engine.game import Game
from shengji.engine.legal import suit_cards
from shengji.state_replay import DEEP_LEAD_STATE_SCHEMA, replay_deep_lead


SCHEMA = "pair-ballot-affected-state-v2"
SHARD_SCHEMA = "pair-ballot-affected-shard-v2"
ARTIFACT_SCHEMA = "pair-ballot-affected-population-v2"
SPLITS = ("dev", "calib", "report")
BANDS = ("early", "mid", "late")
QUOTA_PER_SPLIT = {"early": 448, "mid": 48, "late": 16}
ROWS_PER_SPLIT = sum(QUOTA_PER_SPLIT.values())
TOTAL_ROWS = len(SPLITS) * ROWS_PER_SPLIT
SHARD_COUNT = 16
SEED0 = 310_000_000
MAX_DEALS = 12_000_000
SALT = "pair-ballot-affected-v2"
SOURCE_POLICY = "smart"
DECLARATION_DRIVER = "deal-pass-plus-production-final-pass"
DOSE_ESTIMATOR = "all-search-reachable-omissions-in-full-capture-stream"
RUNTIME_FIELDS = {
    "git", "tree_dirty", "host", "python", "fast_engine", "score_free",
    "outcomes_computed", "strength_claim", "production_authority",
}
SOURCE_FIELDS = {
    "producer", "mcbot", "smart", "engine_game", "engine_legal",
    "state_replay",
}
SHARD_FIELDS = {
    "schema", *RUNTIME_FIELDS, "source_sha256s", "source_policy",
    "declaration_driver", "dose_estimator", "salt", "seed0", "max_deals",
    "seed_ceiling_exclusive", "shard_index", "shard_count", "deals_scanned",
    "observed_by_cell", "eligible_observed_by_cell", "rows",
    "artifact_sha256",
}
ARTIFACT_FIELDS = {
    "schema", *RUNTIME_FIELDS, "source_sha256s", "source_policy",
    "declaration_driver", "dose_estimator", "salt", "seed0", "max_deals",
    "seed_ceiling_exclusive", "shard_count", "selection",
    "split_assignment", "cluster_unit", "rows_per_split", "total_rows",
    "cell_counts", "capture_observed_by_cell",
    "capture_search_eligible_by_cell", "search_eligible_counts_by_band",
    "search_eligible_denominator", "search_eligible_weights", "unique_deals",
    "max_states_per_deal", "shards", "states", "artifact_sha256",
}


class CaptureRefused(RuntimeError):
    """The score-free population or its deterministic identity drifted."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | os.PathLike) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True,
    ).stdout.strip()


def split_for_seed(seed: int) -> str:
    digest = hashlib.sha256(f"{SALT}|split|{seed}".encode()).digest()
    return SPLITS[int.from_bytes(digest[:8], "big") % len(SPLITS)]


def band_for_trick(trick: int) -> str:
    return "early" if trick < 4 else ("mid" if trick < 12 else "late")


def cell_name(split: str, band: str) -> str:
    return f"{split}/{band}"


def all_cells() -> tuple[str, ...]:
    return tuple(cell_name(split, band) for split in SPLITS for band in BANDS)


def pair_actions(rnd, seat: int) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    assert rnd.ordering is not None
    for suit in list(SUITS) + [TRUMP]:
        cards = suit_cards(rnd.hands[seat], suit, rnd.ordering)
        pairs.update((code, code) for code, count in Counter(cards).items()
                     if count >= 2)
    return pairs


def action_key(cards) -> tuple[str, ...]:
    return tuple(sorted(cards))


def ballot_delta(current, retained) -> tuple[list[list[str]], list[list[str]]]:
    current_keys = {action_key(cards) for cards in current}
    retained_keys = {action_key(cards) for cards in retained}
    inserted = [list(cards) for cards in retained
                if action_key(cards) not in current_keys]
    evicted = [list(cards) for cards in current
               if action_key(cards) not in retained_keys]
    return inserted, evicted


def search_reachable(bot, rnd, seat: int) -> bool:
    """Whether ``MCBot.decide_play`` reaches candidate generation/search."""
    if not bot.TRACTOR_LOCK:
        return True
    canonical = bot.canonical_lead(rnd, seat)
    dec = decompose(canonical, rnd.ordering)
    return not (len(dec.components) == 1
                and dec.components[0].pair_len >= 2)


def replay_payload(*, seed: int, split: str, rnd, seat: int,
                   setup: dict, plays: list[dict]) -> dict:
    role = "attacker" if rnd.is_attacker(seat) else "defender"
    return {
        "schema": DEEP_LEAD_STATE_SCHEMA,
        "seed": seed,
        "split": split,
        "trick": len(rnd.history),
        "role": role,
        "seat": seat,
        "ply": len(plays),
        "setup": setup,
        "plays": list(plays),
    }


def state_record(*, seed: int, split: str, rnd, seat: int,
                 setup: dict, plays: list[dict], current: list[list[str]],
                 retained: list[list[str]], missing: set[tuple[str, str]],
                 search_eligible: bool) -> dict:
    band = band_for_trick(len(rnd.history))
    inserted, evicted = ballot_delta(current, retained)
    replay = replay_payload(
        seed=seed, split=split, rnd=rnd, seat=seat, setup=setup, plays=plays)
    row = {
        "schema": SCHEMA,
        "state_id": f"{seed}:{len(rnd.history)}:{seat}",
        "deal_seed": seed,
        "split": split,
        "band": band,
        "trick": len(rnd.history),
        "seat": seat,
        "role": replay["role"],
        "search_eligible": search_eligible,
        "current_ballot": [list(cards) for cards in current],
        "retained_ballot": [list(cards) for cards in retained],
        "missing_pairs": [list(cards) for cards in sorted(missing)],
        "inserted_actions": inserted,
        "evicted_actions": evicted,
        "replay": replay,
    }
    row["state_sha256"] = sha256_bytes(canonical_json(row))
    validate_state_record(row)
    return row


def replay_state(row: dict):
    validate_state_record(row, replay=False)
    rnd = replay_deep_lead(row["replay"])
    validate_state_record(row, rnd=rnd, replay=False)
    return rnd


def validate_state_record(row: object, *, rnd=None,
                          replay: bool = True) -> None:
    if not isinstance(row, dict) or row.get("schema") != SCHEMA:
        raise CaptureRefused("affected-state schema drift")
    body = dict(row)
    observed_sha = body.pop("state_sha256", None)
    if observed_sha != sha256_bytes(canonical_json(body)):
        raise CaptureRefused("affected-state digest drift")
    expected_fields = {
        "schema", "state_id", "deal_seed", "split", "band", "trick",
        "seat", "role", "search_eligible", "current_ballot", "retained_ballot",
        "missing_pairs", "inserted_actions", "evicted_actions", "replay",
        "state_sha256",
    }
    if set(row) != expected_fields:
        raise CaptureRefused("affected-state field population drift")
    seed = row.get("deal_seed")
    trick = row.get("trick")
    seat = row.get("seat")
    if (isinstance(seed, bool) or not isinstance(seed, int)
            or isinstance(trick, bool) or not isinstance(trick, int)
            or isinstance(seat, bool) or not isinstance(seat, int)
            or not 0 <= seat < 4):
        raise CaptureRefused("affected-state scalar identity drift")
    if not isinstance(row.get("search_eligible"), bool):
        raise CaptureRefused("affected-state search eligibility drift")
    if (row.get("split") != split_for_seed(seed)
            or row.get("band") != band_for_trick(trick)
            or row.get("state_id") != f"{seed}:{trick}:{seat}"):
        raise CaptureRefused("affected-state split/band identity drift")
    replay_row = row.get("replay")
    if (not isinstance(replay_row, dict)
            or replay_row.get("schema") != DEEP_LEAD_STATE_SCHEMA
            or replay_row.get("seed") != seed
            or replay_row.get("split") != row.get("split")
            or replay_row.get("trick") != trick
            or replay_row.get("seat") != seat
            or replay_row.get("role") != row.get("role")):
        raise CaptureRefused("affected-state replay identity drift")
    current = row.get("current_ballot")
    retained = row.get("retained_ballot")
    if (not isinstance(current, list) or not isinstance(retained, list)
            or len(current) != len(retained) or not current
            or action_key(current[0]) != action_key(retained[0])):
        raise CaptureRefused("affected-state equal-width/candidate-zero drift")
    current_keys = [action_key(cards) for cards in current]
    retained_keys = [action_key(cards) for cards in retained]
    if (len(current_keys) != len(set(current_keys))
            or len(retained_keys) != len(set(retained_keys))):
        raise CaptureRefused("affected-state duplicate ballot action")
    missing = {action_key(cards) for cards in row.get("missing_pairs", [])}
    inserted = [action_key(cards) for cards in row.get("inserted_actions", [])]
    evicted = [action_key(cards) for cards in row.get("evicted_actions", [])]
    if (not missing or not missing <= set(inserted)
            or set(inserted) != set(retained_keys) - set(current_keys)
            or set(evicted) != set(current_keys) - set(retained_keys)
            or len(inserted) != len(evicted)):
        raise CaptureRefused("affected-state ballot delta drift")
    if rnd is None and replay:
        rnd = replay_deep_lead(replay_row)
    if rnd is not None:
        if (rnd.turn != seat or rnd.trick is None or rnd.trick.plays
                or len(rnd.history) != trick):
            raise CaptureRefused("affected-state replay boundary drift")
        role = "attacker" if rnd.is_attacker(seat) else "defender"
        if role != row.get("role"):
            raise CaptureRefused("affected-state replay role drift")
        current_bot = make_bot("mc", seed=0)
        retained_bot = make_bot("mc", seed=0)
        retained_bot.RETAIN_ALL_LEAD_PAIRS = True
        observed_current = current_bot._candidates(rnd, seat)
        observed_retained = retained_bot._candidates(rnd, seat)
        if ([action_key(cards) for cards in observed_current] != current_keys
                or [action_key(cards) for cards in observed_retained]
                != retained_keys):
            raise CaptureRefused("affected-state ballot replay drift")
        observed_missing = pair_actions(rnd, seat) - set(current_keys)
        if observed_missing != missing:
            raise CaptureRefused("affected-state missing-pair replay drift")
        if search_reachable(current_bot, rnd, seat) != row["search_eligible"]:
            raise CaptureRefused("affected-state search eligibility replay drift")


def _deal_rows(seed: int, *, observed: Counter | None = None,
               eligible_observed: Counter | None = None) -> list[dict]:
    split = split_for_seed(seed)
    game = Game(random.Random(seed))
    actors = [make_bot(SOURCE_POLICY) for _ in range(4)]
    current_bot = make_bot("mc", seed=0)
    retained_bot = make_bot("mc", seed=0)
    retained_bot.RETAIN_ALL_LEAD_PAIRS = True
    rnd = game.start_round()
    initial_banker = rnd.banker
    declarations = []
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = actors[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({
                "stage": "deal", "deal_pos": rnd._deal_pos,
                "seat": seat, "cards": list(cards),
            })
    # Match shengji.ai.env.play_round exactly. The first census omitted this
    # production grace-window pass, so its counts describe a useful synthetic
    # trajectory but not the literal live declaration distribution.
    for seat in range(4):
        cards = actors[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({
                "stage": "final", "deal_pos": rnd._deal_pos,
                "seat": seat, "cards": list(cards),
            })
    rnd.finalize_declare()
    assert rnd.banker is not None
    final_declaration = None if rnd.declaration is None else {
        "seat": rnd.declaration["seat"],
        "cards": list(rnd.declaration["cards"]),
        "strength": rnd.declaration["strength"],
    }
    buried = list(actors[rnd.banker].decide_bury(rnd, rnd.banker))
    setup = {
        "deck": list(rnd.deck),
        "initial_banker": initial_banker,
        "trump_rank": rnd.trump_rank,
        "banker": rnd.banker,
        "trump_suit": rnd.trump_suit,
        "trump_is_nt": rnd.trump_is_nt,
        "declarations": declarations,
        "final_declaration": final_declaration,
        "buried": buried,
    }
    rnd.bury(rnd.banker, buried)
    plays: list[dict] = []
    kept_bands: set[str] = set()
    rows = []
    while rnd.phase == "play":
        seat = rnd.turn
        if seat is None:
            break
        assert rnd.trick is not None
        if not rnd.trick.plays:
            band = band_for_trick(len(rnd.history))
            current = current_bot._candidates(rnd, seat)
            retained = retained_bot._candidates(rnd, seat)
            current_keys = {action_key(cards) for cards in current}
            missing = pair_actions(rnd, seat) - current_keys
            if missing:
                eligible = search_reachable(current_bot, rnd, seat)
                cell = cell_name(split, band)
                if observed is not None:
                    observed[cell] += 1
                if eligible and eligible_observed is not None:
                    eligible_observed[cell] += 1
                if band not in kept_bands:
                    rows.append(state_record(
                        seed=seed, split=split, rnd=rnd, seat=seat,
                        setup=setup, plays=plays, current=current,
                        retained=retained, missing=missing,
                        search_eligible=eligible))
                    kept_bands.add(band)
        cards = actors[seat].decide_play(rnd, seat)
        rnd.play(seat, cards)
        plays.append({"seat": seat, "cards": list(cards)})
    return rows


def _source_sha256s() -> dict[str, str]:
    import shengji.ai.mcbot as mcbot
    import shengji.ai.smart as smart
    import shengji.engine.game as game
    import shengji.engine.legal as legal
    import shengji.state_replay as state_replay

    return {
        name: sha256_file(path) for name, path in sorted({
            "producer": __file__,
            "mcbot": mcbot.__file__,
            "smart": smart.__file__,
            "engine_game": game.__file__,
            "engine_legal": legal.__file__,
            "state_replay": state_replay.__file__,
        }.items())
    }


def _runtime(*, smoke: bool) -> dict:
    dirty = bool(git("status", "--porcelain", "--untracked-files=all"))
    if dirty and not smoke:
        raise CaptureRefused("real capture refuses a dirty tree")
    if not smoke:
        from shengji.engine import combos, fast
        if (os.environ.get("SHENGJI_FAST") != "1" or not fast.HAVE_FAST
                or combos.decompose is not fast.decompose):
            raise CaptureRefused(
                "real capture requires SHENGJI_FAST=1 and compiled routing")
    return {
        "git": git("rev-parse", "HEAD"),
        "tree_dirty": dirty,
        "host": platform.node(),
        "python": platform.python_version(),
        "fast_engine": os.environ.get("SHENGJI_FAST") == "1",
        "score_free": True,
        "outcomes_computed": False,
        "strength_claim": False,
        "production_authority": False,
    }


def _write_exclusive(path: Path, payload: object) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise CaptureRefused(f"refusing existing output {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with partial.open("xb") as handle:
            handle.write(canonical_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
        # Publish by hard link so a target created after the pre-check cannot
        # be silently overwritten.  Capture populations are one-shot assets.
        os.link(partial, path)
        partial.unlink()
    except Exception:
        if partial.exists() and not path.exists():
            partial.unlink()
        raise


def shard_path(base: Path, index: int, count: int) -> Path:
    return base.with_name(f"{base.stem}.shard-{index:02d}-of-{count:02d}.json")


def capture_shard(*, shard_index: int, shard_count: int, seed0: int,
                  max_deals: int, out: Path, smoke: bool = False,
                  progress_every: int = 10_000) -> dict:
    if not 0 <= shard_index < shard_count:
        raise CaptureRefused("shard index must satisfy 0 <= index < count")
    if not smoke and (seed0 != SEED0 or max_deals != MAX_DEALS
                      or shard_count != SHARD_COUNT):
        raise CaptureRefused("real capture seed population drift")
    runtime = _runtime(smoke=smoke)
    local = defaultdict(list)
    scanned = 0
    observed = Counter()
    eligible_observed = Counter()
    for seed in range(seed0 + shard_index, seed0 + max_deals, shard_count):
        scanned += 1
        for row in _deal_rows(
                seed, observed=observed,
                eligible_observed=eligible_observed):
            cell = cell_name(row["split"], row["band"])
            if (row["search_eligible"]
                    and len(local[cell]) < QUOTA_PER_SPLIT[row["band"]]):
                local[cell].append(row)
        if progress_every and scanned % progress_every == 0:
            print(json.dumps({
                "event": "pair-affected-capture-progress-v1",
                "shard_index": shard_index,
                "shard_count": shard_count,
                "deals_scanned": scanned,
                "rows_kept": sum(map(len, local.values())),
                "score_free": True,
            }, sort_keys=True), flush=True)
    rows = sorted(
        (row for values in local.values() for row in values),
        key=lambda row: (row["deal_seed"], row["trick"], row["seat"]),
    )
    payload = {
        "schema": SHARD_SCHEMA,
        **runtime,
        "source_sha256s": _source_sha256s(),
        "source_policy": SOURCE_POLICY,
        "declaration_driver": DECLARATION_DRIVER,
        "dose_estimator": DOSE_ESTIMATOR,
        "salt": SALT,
        "seed0": seed0,
        "max_deals": max_deals,
        "seed_ceiling_exclusive": seed0 + max_deals,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "deals_scanned": scanned,
        "observed_by_cell": dict(sorted(observed.items())),
        "eligible_observed_by_cell": dict(sorted(eligible_observed.items())),
        "rows": rows,
    }
    payload["artifact_sha256"] = sha256_bytes(canonical_json(payload))
    target = shard_path(out, shard_index, shard_count)
    _write_exclusive(target, payload)
    return payload


def validate_shard(payload: object, *, shard_index: int, shard_count: int,
                   seed0: int, max_deals: int,
                   expected_runtime: dict | None = None,
                   smoke: bool = False) -> None:
    if not isinstance(payload, dict) or payload.get("schema") != SHARD_SCHEMA:
        raise CaptureRefused("pair capture shard schema drift")
    if set(payload) != SHARD_FIELDS:
        raise CaptureRefused("pair capture shard field population drift")
    body = dict(payload)
    observed_sha = body.pop("artifact_sha256", None)
    if observed_sha != sha256_bytes(canonical_json(body)):
        raise CaptureRefused("pair capture shard digest drift")
    exact = {
        "source_policy": SOURCE_POLICY,
        "declaration_driver": DECLARATION_DRIVER,
        "dose_estimator": DOSE_ESTIMATOR,
        "salt": SALT,
        "seed0": seed0,
        "max_deals": max_deals,
        "seed_ceiling_exclusive": seed0 + max_deals,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "deals_scanned": len(range(
            seed0 + shard_index, seed0 + max_deals, shard_count)),
        "score_free": True,
        "outcomes_computed": False,
        "strength_claim": False,
        "production_authority": False,
    }
    if any(payload.get(key) != value for key, value in exact.items()):
        raise CaptureRefused("pair capture shard identity/authority drift")
    if not smoke and (payload.get("tree_dirty") is not False
                      or payload.get("fast_engine") is not True):
        raise CaptureRefused("pair capture shard runtime authority drift")
    if expected_runtime is not None and any(
            payload.get(key) != expected_runtime.get(key)
            for key in RUNTIME_FIELDS):
        raise CaptureRefused("pair capture shard runtime cohort drift")
    source_sha256s = payload.get("source_sha256s")
    if (not isinstance(source_sha256s, dict)
            or set(source_sha256s) != SOURCE_FIELDS
            or any(not isinstance(value, str) or len(value) != 64
                   for value in source_sha256s.values())):
        raise CaptureRefused("pair capture shard source identity drift")
    if source_sha256s != _source_sha256s():
        raise CaptureRefused("pair capture shard executable source drift")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise CaptureRefused("pair capture shard rows missing")
    observed = payload.get("observed_by_cell")
    eligible_observed = payload.get("eligible_observed_by_cell")
    if (not isinstance(observed, dict)
            or not isinstance(eligible_observed, dict)
            or any(cell not in all_cells() for cell in observed)
            or any(cell not in all_cells() for cell in eligible_observed)
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0
                   for value in [*observed.values(),
                                 *eligible_observed.values()])
            or any(eligible_observed.get(cell, 0) > observed.get(cell, 0)
                   for cell in all_cells())):
        raise CaptureRefused("pair capture observed-count accounting drift")
    seen = set()
    counts = Counter()
    for row in rows:
        replay_state(row)
        seed = row["deal_seed"]
        if ((seed - seed0) % shard_count != shard_index
                or not seed0 <= seed < seed0 + max_deals):
            raise CaptureRefused("pair capture row outside shard seed stream")
        key = row["state_id"]
        if key in seen:
            raise CaptureRefused("pair capture duplicate state in shard")
        seen.add(key)
        cell = cell_name(row["split"], row["band"])
        counts[cell] += 1
        if counts[cell] > QUOTA_PER_SPLIT[row["band"]]:
            raise CaptureRefused("pair capture shard exceeded local cell cap")
        if row["search_eligible"] is not True:
            raise CaptureRefused("pair capture retained a search-unreachable row")
    if any(counts[cell] > eligible_observed.get(cell, 0)
           for cell in all_cells()):
        raise CaptureRefused("pair capture retained count exceeds observations")
    if rows != sorted(rows, key=lambda row: (
            row["deal_seed"], row["trick"], row["seat"])):
        raise CaptureRefused("pair capture shard row order drift")


def select_population(rows: list[dict], *,
                      quotas: dict[str, int] | None = None
                      ) -> tuple[list[dict], dict[str, int]]:
    """Select the globally earliest rows per split/band, shard-order free."""
    quotas = dict(QUOTA_PER_SPLIT if quotas is None else quotas)
    if set(quotas) != set(BANDS) or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in quotas.values()):
        raise CaptureRefused("pair capture quota schema drift")
    by_cell = defaultdict(list)
    for row in rows:
        by_cell[cell_name(row["split"], row["band"])].append(row)
    selected = []
    shortages = {}
    for split in SPLITS:
        for band in BANDS:
            cell = cell_name(split, band)
            candidates = sorted(by_cell[cell], key=lambda row: (
                row["deal_seed"], row["trick"], row["seat"]))
            want = quotas[band]
            if len(candidates) < want:
                shortages[cell] = want - len(candidates)
            selected.extend(candidates[:want])
    selected.sort(key=lambda row: (
        row["deal_seed"], row["trick"], row["seat"]))
    return selected, shortages


def merge_shards(*, shard_count: int, seed0: int, max_deals: int,
                 out: Path, smoke: bool = False) -> dict:
    if not smoke and (seed0 != SEED0 or max_deals != MAX_DEALS
                      or shard_count != SHARD_COUNT):
        raise CaptureRefused("real merge seed population drift")
    runtime = _runtime(smoke=smoke)
    rows = []
    shard_receipts = []
    source_sha256s = None
    observed_by_cell = Counter()
    eligible_observed_by_cell = Counter()
    for index in range(shard_count):
        path = shard_path(out, index, shard_count)
        if path.is_symlink() or not path.is_file():
            raise CaptureRefused(f"missing/nonregular shard {index}")
        payload = json.loads(path.read_bytes())
        validate_shard(
            payload, shard_index=index, shard_count=shard_count,
            seed0=seed0, max_deals=max_deals,
            expected_runtime=runtime, smoke=smoke)
        if source_sha256s is None:
            source_sha256s = payload.get("source_sha256s")
        elif payload.get("source_sha256s") != source_sha256s:
            raise CaptureRefused("pair capture source digest drift across shards")
        rows.extend(payload["rows"])
        observed_by_cell.update(payload.get("observed_by_cell", {}))
        eligible_observed_by_cell.update(
            payload.get("eligible_observed_by_cell", {}))
        shard_receipts.append({
            "shard_index": index,
            "path": path.name,
            "file_sha256": sha256_file(path),
            "artifact_sha256": payload["artifact_sha256"],
            "deals_scanned": payload["deals_scanned"],
        })
    selected, shortages = select_population(rows)
    if shortages:
        raise CaptureRefused(f"pair capture population short: {shortages}")
    ids = [row["state_id"] for row in selected]
    if len(ids) != len(set(ids)) or len(selected) != TOTAL_ROWS:
        raise CaptureRefused("pair capture merged population identity drift")
    counts = Counter(cell_name(row["split"], row["band"])
                     for row in selected)
    expected_counts = {
        cell_name(split, band): QUOTA_PER_SPLIT[band]
        for split in SPLITS for band in BANDS
    }
    if dict(sorted(counts.items())) != expected_counts:
        raise CaptureRefused("pair capture merged cell counts drift")
    deal_counts = Counter(row["deal_seed"] for row in selected)
    eligible_by_band = {
        band: sum(eligible_observed_by_cell[cell_name(split, band)]
                  for split in SPLITS)
        for band in BANDS
    }
    eligible_total = sum(eligible_by_band.values())
    if eligible_total <= 0:
        raise CaptureRefused("pair capture observed no search-reachable omissions")
    payload = {
        "schema": ARTIFACT_SCHEMA,
        **runtime,
        "source_sha256s": source_sha256s,
        "source_policy": SOURCE_POLICY,
        "declaration_driver": DECLARATION_DRIVER,
        "dose_estimator": DOSE_ESTIMATOR,
        "salt": SALT,
        "seed0": seed0,
        "max_deals": max_deals,
        "seed_ceiling_exclusive": seed0 + max_deals,
        "shard_count": shard_count,
        "selection": "globally earliest affected states per split/band",
        "split_assignment": "sha256(salt|split|deal_seed) before play",
        "cluster_unit": "deal_seed",
        "rows_per_split": ROWS_PER_SPLIT,
        "total_rows": TOTAL_ROWS,
        "cell_counts": expected_counts,
        "capture_observed_by_cell": dict(sorted(observed_by_cell.items())),
        "capture_search_eligible_by_cell": dict(
            sorted(eligible_observed_by_cell.items())),
        "search_eligible_counts_by_band": eligible_by_band,
        "search_eligible_denominator": eligible_total,
        "search_eligible_weights": {
            band: eligible_by_band[band] / eligible_total for band in BANDS
        },
        "unique_deals": len(deal_counts),
        "max_states_per_deal": max(deal_counts.values()),
        "shards": shard_receipts,
        "states": selected,
    }
    payload["artifact_sha256"] = sha256_bytes(canonical_json(payload))
    _write_exclusive(out, payload)
    return payload


def validate_population(payload: object, *, replay: bool = True) -> None:
    """Fully reopen the merged asset rather than trusting its self-hash."""
    if (not isinstance(payload, dict)
            or payload.get("schema") != ARTIFACT_SCHEMA):
        raise CaptureRefused("population schema drift")
    if set(payload) != ARTIFACT_FIELDS:
        raise CaptureRefused("population field population drift")
    body = dict(payload)
    observed_sha = body.pop("artifact_sha256", None)
    if observed_sha != sha256_bytes(canonical_json(body)):
        raise CaptureRefused("population digest drift")
    exact = {
        "tree_dirty": False,
        "fast_engine": True,
        "score_free": True,
        "outcomes_computed": False,
        "strength_claim": False,
        "production_authority": False,
        "source_policy": SOURCE_POLICY,
        "declaration_driver": DECLARATION_DRIVER,
        "dose_estimator": DOSE_ESTIMATOR,
        "salt": SALT,
        "seed0": SEED0,
        "max_deals": MAX_DEALS,
        "seed_ceiling_exclusive": SEED0 + MAX_DEALS,
        "shard_count": SHARD_COUNT,
        "selection": "globally earliest affected states per split/band",
        "split_assignment": "sha256(salt|split|deal_seed) before play",
        "cluster_unit": "deal_seed",
        "rows_per_split": ROWS_PER_SPLIT,
        "total_rows": TOTAL_ROWS,
    }
    if any(payload.get(key) != value for key, value in exact.items()):
        raise CaptureRefused("population identity/authority drift")
    source_sha256s = payload.get("source_sha256s")
    if (not isinstance(source_sha256s, dict)
            or set(source_sha256s) != SOURCE_FIELDS
            or source_sha256s != _source_sha256s()):
        raise CaptureRefused("population executable source drift")
    expected_counts = {
        cell_name(split, band): QUOTA_PER_SPLIT[band]
        for split in SPLITS for band in BANDS
    }
    if payload.get("cell_counts") != expected_counts:
        raise CaptureRefused("population cell-count drift")
    observed = payload.get("capture_observed_by_cell")
    eligible = payload.get("capture_search_eligible_by_cell")
    if (not isinstance(observed, dict) or not isinstance(eligible, dict)
            or any(cell not in all_cells() for cell in observed)
            or any(cell not in all_cells() for cell in eligible)
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0 for value in [*observed.values(),
                                              *eligible.values()])
            or any(eligible.get(cell, 0) > observed.get(cell, 0)
                   for cell in all_cells())):
        raise CaptureRefused("population observation accounting drift")
    by_band = payload.get("search_eligible_counts_by_band")
    denominator = payload.get("search_eligible_denominator")
    weights = payload.get("search_eligible_weights")
    expected_by_band = {
        band: sum(eligible.get(cell_name(split, band), 0)
                  for split in SPLITS)
        for band in BANDS
    }
    if (by_band != expected_by_band
            or isinstance(denominator, bool)
            or not isinstance(denominator, int)
            or denominator != sum(expected_by_band.values())
            or denominator <= 0
            or not isinstance(weights, dict) or set(weights) != set(BANDS)
            or any(not isinstance(value, (int, float))
                   or isinstance(value, bool) or not math.isfinite(value)
                   or value <= 0 for value in weights.values())
            or any(not math.isclose(
                weights[band], expected_by_band[band] / denominator,
                rel_tol=0.0, abs_tol=1e-15) for band in BANDS)
            or not math.isclose(sum(weights.values()), 1.0,
                                rel_tol=0.0, abs_tol=1e-15)):
        raise CaptureRefused("population natural-dose weights drift")
    receipts = payload.get("shards")
    if (not isinstance(receipts, list) or len(receipts) != SHARD_COUNT
            or [item.get("shard_index") for item in receipts]
            != list(range(SHARD_COUNT))):
        raise CaptureRefused("population shard receipt set drift")
    receipt_prefixes = set()
    for index, receipt in enumerate(receipts):
        expected_receipt_fields = {
            "shard_index", "path", "file_sha256", "artifact_sha256",
            "deals_scanned",
        }
        if (not isinstance(receipt, dict)
                or set(receipt) != expected_receipt_fields
                or not isinstance(receipt.get("path"), str)
                or not receipt["path"].endswith(
                    f".shard-{index:02d}-of-{SHARD_COUNT:02d}.json")
                or receipt.get("deals_scanned") != len(range(
                    SEED0 + index, SEED0 + MAX_DEALS, SHARD_COUNT))
                or any(not isinstance(receipt.get(field), str)
                       or len(receipt[field]) != 64
                       for field in ("file_sha256", "artifact_sha256"))):
            raise CaptureRefused("population shard receipt drift")
        receipt_prefixes.add(receipt["path"].rsplit(".shard-", 1)[0])
    if len(receipt_prefixes) != 1:
        raise CaptureRefused("population shard receipt namespace drift")
    rows = payload.get("states")
    if not isinstance(rows, list) or len(rows) != TOTAL_ROWS:
        raise CaptureRefused("population state count drift")
    ids = []
    counts = Counter()
    deal_counts = Counter()
    for row in rows:
        validate_state_record(row, replay=replay)
        if row.get("search_eligible") is not True:
            raise CaptureRefused("population retained search-unreachable state")
        ids.append(row["state_id"])
        counts[cell_name(row["split"], row["band"])] += 1
        deal_counts[row["deal_seed"]] += 1
    if (len(ids) != len(set(ids))
            or dict(sorted(counts.items())) != expected_counts
            or payload.get("unique_deals") != len(deal_counts)
            or payload.get("max_states_per_deal") != max(deal_counts.values())
            or rows != sorted(rows, key=lambda row: (
                row["deal_seed"], row["trick"], row["seat"]))):
        raise CaptureRefused("population state identity/order drift")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("mode", choices=("capture", "merge", "verify"))
    result.add_argument("--out", type=Path, required=True)
    result.add_argument("--shard-index", type=int, default=0)
    result.add_argument("--shard-count", type=int, default=SHARD_COUNT)
    result.add_argument("--seed0", type=int, default=SEED0)
    result.add_argument("--max-deals", type=int, default=MAX_DEALS)
    result.add_argument("--progress-every", type=int, default=10_000)
    result.add_argument("--smoke", action="store_true")
    return result


def main() -> None:
    args = parser().parse_args()
    if args.shard_count <= 0 or args.max_deals <= 0:
        raise SystemExit("shard-count and max-deals must be positive")
    try:
        if args.mode == "capture":
            capture_shard(
                shard_index=args.shard_index, shard_count=args.shard_count,
                seed0=args.seed0, max_deals=args.max_deals, out=args.out,
                smoke=args.smoke, progress_every=args.progress_every)
        elif args.mode == "merge":
            merge_shards(
                shard_count=args.shard_count, seed0=args.seed0,
                max_deals=args.max_deals, out=args.out, smoke=args.smoke)
        else:
            if args.out.is_symlink() or not args.out.is_file():
                raise CaptureRefused("population missing/nonregular")
            payload = json.loads(args.out.read_bytes())
            validate_population(payload)
            print(json.dumps({
                "verified": True,
                "artifact_sha256": sha256_file(args.out),
                "rows": len(payload.get("states", [])),
                "score_free": payload["score_free"],
            }, sort_keys=True))
    except (CaptureRefused, ValueError) as exc:
        print(f"REFUSING: {exc}")
        raise SystemExit(3) from exc


if __name__ == "__main__":
    main()
