"""Falsification boundary for the non-authorizing PR71 receipt."""
from __future__ import annotations

import copy
import functools
import hashlib
import importlib.util
import json
import linecache
import os
import platform
import subprocess
import sys
import types
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / \
    "pr71_policy_compatibility.py"
SPEC = importlib.util.spec_from_file_location("pr71_compat", SCRIPT)
assert SPEC and SPEC.loader
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)

SERVER = Path(__file__).parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))

from shengji.ai import heuristic  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.evaluation import arm_ballots  # noqa: E402

COMPATIBILITY_FILES = {
    "server/scripts/pr71_policy_compatibility.py",
    "server/scripts/pr71_policy_compatibility.v1.json",
    "server/tests/test_pr71_policy_compatibility.py",
}
POLICY_RUNTIME_AVAILABLE = (
    os.environ.get("SHENGJI_FAST") == "1"
    and platform.python_version() == C.POLICY_CONTRACT_RUNTIME["python"]
    and platform.system() == C.POLICY_CONTRACT_RUNTIME["system"]
    and platform.machine() == C.POLICY_CONTRACT_RUNTIME["machine"]
)


def _git_bytes(revision: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{revision}:{path}"], cwd=REPO, check=True,
        capture_output=True,
    ).stdout


def _git_text(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=list,
    ).encode()).hexdigest()


def _policy_contract(name: str) -> dict:
    bot = make_bot(name, seed=7)
    uppercase = {
        field: getattr(bot, field) for field in dir(bot)
        if field.isupper() and isinstance(
            getattr(bot, field), (bool, int, float, str, type(None)))
    }
    return {
        "policy": name,
        "class": type(bot).__name__,
        "uppercase": uppercase,
        "rollout_policy_class": type(bot.rollout_policy).__name__,
        "ballot": arm_ballots([name])[name],
    }


def _contract_digests() -> tuple[dict, dict, set[str]]:
    full, non_ballot, ballots = {}, {}, set()
    for name in C.POLICIES:
        contract = _policy_contract(name)
        full[name] = _digest(contract)
        ballots.add(contract.pop("ballot"))
        non_ballot[name] = _digest(contract)
    return full, non_ballot, ballots


@functools.lru_cache(maxsize=1)
def _historical_heuristic_module():
    module = types.ModuleType("shengji.ai._pr71_historical_heuristic")
    module.__package__ = "shengji.ai"
    module.__file__ = f"git:{C.HISTORICAL_GIT}:{C.HEURISTIC_PATH}"
    sys.modules[module.__name__] = module
    source = _git_bytes(C.HISTORICAL_GIT, C.HEURISTIC_PATH).decode()
    # ``engine.ballot`` deliberately fingerprints live callable source.  Give
    # inspect.getsource the exact historical text rather than an opaque
    # synthetic-module fallback so this independently reconstructs a68/59fa.
    linecache.cache[module.__file__] = (
        len(source), None, source.splitlines(keepends=True), module.__file__)
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def _lead_before_prefilter(hand, trump_suit, trump_rank):
    import random
    from shengji.engine.cards import Ordering
    from shengji.engine.round import Round

    historical = _historical_heuristic_module()
    rnd = Round(trump_rank, 0, random.Random(0))
    rnd.ordering = Ordering(trump_suit, trump_rank)
    rnd.hands[0] = list(hand)
    return historical.HeuristicBot()._lead(rnd, 0)


def _lead_current(hand, trump_suit, trump_rank):
    import random
    from shengji.engine.cards import Ordering
    from shengji.engine.round import Round

    rnd = Round(trump_rank, 0, random.Random(0))
    rnd.ordering = Ordering(trump_suit, trump_rank)
    rnd.hands[0] = list(hand)
    return heuristic.HeuristicBot()._lead(rnd, 0)


@pytest.mark.skipif(
    not POLICY_RUNTIME_AVAILABLE,
    reason="exact historical policy-contract runtime is unavailable",
)
def test_receipt_reopens_exact_old_new_sources_and_current_contracts(
        monkeypatch: pytest.MonkeyPatch):
    assert hashlib.sha256(_git_bytes(
        C.HISTORICAL_GIT, C.HEURISTIC_PATH)).hexdigest() == \
        C.HISTORICAL_HEURISTIC_SHA256
    assert hashlib.sha256((SERVER / "shengji/ai/heuristic.py").read_bytes()
                          ).hexdigest() == C.CURRENT_HEURISTIC_SHA256
    assert os.environ.get("SHENGJI_FAST") == "1"
    current_full, current_non_ballot, current_ballots = _contract_digests()
    assert current_full == C.CURRENT_POLICY_CONTRACT_SHA256S
    assert current_non_ballot == C.NON_BALLOT_POLICY_CONTRACT_SHA256S
    assert current_ballots == {C.CURRENT_BALLOT}

    historical = _historical_heuristic_module()
    with monkeypatch.context() as patch:
        patch.setattr(
            heuristic.HeuristicBot, "_lead", historical.HeuristicBot._lead)
        patch.setattr(heuristic.HeuristicBot, "_current_winner",
                      historical.HeuristicBot._current_winner)
        historical_full, historical_non_ballot, historical_ballots = \
            _contract_digests()
    assert historical_full == C.HISTORICAL_POLICY_CONTRACT_SHA256S
    assert historical_non_ballot == C.NON_BALLOT_POLICY_CONTRACT_SHA256S
    assert historical_ballots == {C.HISTORICAL_BALLOT}


def test_receipt_commit_is_a_bounded_direct_child_of_exact_pr71():
    assert _git_text("rev-parse", "HEAD^") == C.PARENT_GIT
    assert set(_git_text(
        "diff", "--name-only", f"{C.PARENT_GIT}..HEAD").splitlines()) == \
        COMPATIBILITY_FILES


@pytest.mark.skipif(
    not POLICY_RUNTIME_AVAILABLE,
    reason="exact historical policy-contract runtime is unavailable",
)
def test_receipt_binds_exact_native_identity():
    from shengji.engine import fast

    assert fast.HAVE_FAST
    observed = {
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "fast_binary_sha256": hashlib.sha256(
            Path(fast._fast.__file__).read_bytes()).hexdigest(),
    }
    assert observed == C.POLICY_CONTRACT_RUNTIME


def test_independent_old_new_full_action_parity():
    from shengji.engine.cards import make_deck
    import random

    rng = random.Random(20260812)
    deck = make_deck()
    configs = (("H", "7"), ("S", "2"), ("D", "A"),
               (None, "7"), (None, "A"), ("C", "10"))
    tractors = 0
    for index in range(5_000):
        trump_suit, trump_rank = configs[index % len(configs)]
        hand = rng.sample(deck, rng.randint(1, 33))
        historical = _lead_before_prefilter(hand, trump_suit, trump_rank)
        current = _lead_current(hand, trump_suit, trump_rank)
        assert current == historical
        tractors += len(current) >= 4
    assert tractors >= 100


def _round_evidence(seed: int) -> dict:
    import random
    from shengji.ai.env import play_round
    from shengji.engine import fast
    from shengji.engine.game import Game

    assert fast.activate()
    bots = [make_bot("mc-s0-report-lcb", seed=seed * 100 + seat)
            for seat in range(4)]
    log = play_round(Game(random.Random(seed)), bots, record=True)
    transcript = {
        "seed": seed,
        "policy": "mc-s0-report-lcb",
        "trump_rank": log.trump_rank,
        "banker": log.banker,
        "attacker_points": log.attacker_points,
        "winner_team": log.winner_team,
        "level_change": log.level_change,
        "history": log.history,
    }
    return {
        "transcript_sha256": _digest(transcript),
        "history_plays": len(log.history),
        "rollouts": [bot.rollouts for bot in bots],
        "searches": [bot.search_calls for bot in bots],
        "short_search_decisions": [
            bot.short_search_decisions for bot in bots],
        "zero_world_decisions": [bot.zero_world_decisions for bot in bots],
    }


@pytest.mark.skipif(
    os.environ.get("SHENGJI_PR71_REPLAY") != "1",
    reason="set SHENGJI_PR71_REPLAY=1 for six fixed full-round replays",
)
def test_reproduce_old_new_full_round_transcript_evidence(
        monkeypatch: pytest.MonkeyPatch):
    assert os.environ.get("SHENGJI_FAST") == "1"
    assert os.environ.get("SHENGJI_REQUIRE_VOIDS") == "1"
    assert os.environ.get("PYTHONHASHSEED") == "0"
    assert platform.python_version() == C.PARITY_RUNTIME["python"]
    assert platform.system() == C.PARITY_RUNTIME["system"]
    assert platform.machine() == C.PARITY_RUNTIME["machine"]
    from shengji.engine import fast
    assert hashlib.sha256(Path(fast._fast.__file__).read_bytes()).hexdigest() \
        == C.PARITY_RUNTIME["current_fast_binary_sha256"]
    current = {str(seed): _round_evidence(seed) for seed in C.TRANSCRIPT_SEEDS}

    historical_module = _historical_heuristic_module()
    with monkeypatch.context() as patch:
        patch.setattr(heuristic.HeuristicBot, "_lead",
                      historical_module.HeuristicBot._lead)
        patch.setattr(heuristic.HeuristicBot, "_current_winner",
                      historical_module.HeuristicBot._current_winner)
        historical = {
            str(seed): _round_evidence(seed) for seed in C.TRANSCRIPT_SEEDS}
    assert current == historical == C.TRANSCRIPT_WITNESSES


def test_expected_receipt_is_closed_and_self_hashed():
    receipt = C.expected_receipt()
    assert C.receipt_problems(receipt) == []
    assert C.require_receipt(receipt) == receipt
    assert receipt["historical_rlcb_c1"]["rewritten"] is False
    assert receipt["historical_rlcb_c1"][
        "policy_contract_sha256s"]["mc-s0-report-lcb"] == \
        "59fa033dc22d8a055b5d7f3fbcbaf9d7fb0b71993b74c4d9bb7587e3d90dc72b"
    assert receipt["claim_boundary"] == {
        "compatibility_only": True,
        "historical_evidence_rewritten": False,
        "strength_claim": False,
        "run_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }


def test_committed_receipt_is_canonical_and_exact():
    receipt_path = SCRIPT.with_name("pr71_policy_compatibility.v1.json")
    expected = C.expected_receipt()
    assert receipt_path.read_bytes() == C.canonical_json(expected)
    assert C.require_receipt(json.loads(receipt_path.read_bytes())) == expected


def test_expected_receipt_returns_fresh_nested_values():
    first = C.expected_receipt()
    first["parity_evidence"]["witnesses"]["701"]["rollouts"][0] = -1
    first["parity_evidence"]["environment"]["SHENGJI_FAST"] = "0"
    second = C.expected_receipt()
    assert second["parity_evidence"]["witnesses"]["701"][
        "rollouts"][0] == 10_170
    assert second["parity_evidence"]["environment"]["SHENGJI_FAST"] == "1"


def _leaf_paths(value, prefix=()):
    if isinstance(value, dict):
        return [path for key, child in value.items()
                for path in _leaf_paths(child, (*prefix, key))]
    if isinstance(value, list):
        return [path for index, child in enumerate(value)
                for path in _leaf_paths(child, (*prefix, index))]
    return [prefix]


@pytest.mark.parametrize("path", _leaf_paths(C.expected_receipt()))
def test_every_receipt_leaf_fails_closed_even_with_forged_self_hash(path):
    receipt = copy.deepcopy(C.expected_receipt())
    target = receipt
    for field in path[:-1]:
        target = target[field]
    value = target[path[-1]]
    if isinstance(value, bool):
        target[path[-1]] = not value
    elif isinstance(value, int):
        target[path[-1]] = value + 1
    else:
        target[path[-1]] = "MUTATED"
    # A forged self-hash cannot turn a drifted claim into an accepted receipt.
    if path != ("receipt_sha256",):
        receipt["receipt_sha256"] = C.self_hash(receipt)
    assert C.receipt_problems(receipt)
    with pytest.raises(C.CompatibilityRefused):
        C.require_receipt(receipt)


def test_receipt_module_has_no_execution_or_deploy_surface():
    source = SCRIPT.read_text()
    for forbidden in (
        "play_round(", "run_arm(", "subprocess.Popen", "flyctl",
        "production_promotion\": True", "production_deployment\": True",
        "run_authorized\": True",
    ):
        assert forbidden not in source
