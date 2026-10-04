"""Diagnostic composition for one public fixture and one sampled tape.

This module only composes the reviewed public-root, sampler, legal-pool, and
fixed-tape adapters.  It does not authenticate a model or fixture, read
artifacts, register policies, or make a served-choice claim.
"""

from __future__ import annotations

import copy
from dataclasses import asdict

from ..harvest.legal import enumerate_legal
from .ballot_matrix import _canonical_collection
from .fixed_tape_panel import collect_fixed_tape_panel, collect_history_primed_panel
from .public_refusal_tape import sample_public_refusal_tape


_EFFECTIVE_FIELDS = ("worlds", "cap", "batch_size", "candidates")


def _snapshot_bot(bot, *, seed: int, label: str):
    from ..train.pv_search_policy import PVSearchBot, PVSearchConfig

    if not isinstance(bot, PVSearchBot):
        raise ValueError(f"{label} must be a PVSearchBot")
    config = getattr(bot, "config", None)
    if not isinstance(config, PVSearchConfig):
        raise ValueError(f"{label} must carry a PVSearchConfig")
    checkpoint = getattr(bot, "checkpoint_sha256", None)
    if checkpoint != config.checkpoint_sha256:
        raise ValueError(f"{label} checkpoint/config mismatch")
    effective = {}
    for field in _EFFECTIVE_FIELDS:
        expected = getattr(config, field)
        actual = getattr(bot, field, None)
        if actual != expected:
            raise ValueError(f"{label} {field} differs from config")
        effective[field] = actual
    if type(getattr(bot, "seed", None)) is not int or bot.seed != seed:
        raise ValueError(f"{label} seed differs from requested seed")
    sampler = getattr(bot, "sampler", None)
    if type(getattr(sampler, "seed", None)) is not int or sampler.seed != seed:
        raise ValueError(f"{label} sampler seed differs from requested seed")
    return {
        "config": asdict(config),
        "checkpoint_sha256": checkpoint,
        "effective": effective,
    }


def collect_public_fixture_panel(bot_factory, fixture, control_ballot,
                                 treatment_ballot, *, mode, seed,
                                 fill_seed=0, check_budget=None,
                                 expected_legal_count=None):
    """Compose one declared-mode public tape with complete-pool scoring.

    The caller still owns fixture history, model/runtime, sampler, and legal
    provenance.  A real call is scientific collection requiring its reviewed
    packet and authorization; this helper does not establish those facts.
    """
    if mode not in ("fresh-root", "history-primed"):
        raise ValueError("explicit fresh-root or history-primed mode required")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    if type(fill_seed) is not int or fill_seed < 0:
        raise ValueError("fill_seed must be a nonnegative integer")
    if expected_legal_count is not None and (
            type(expected_legal_count) is not int or expected_legal_count < 1):
        raise ValueError("expected_legal_count must be a positive integer")

    control_input = copy.deepcopy(control_ballot)
    treatment_input = copy.deepcopy(treatment_ballot)
    control = _canonical_collection(control_input, "control_ballot")
    treatment = _canonical_collection(treatment_input, "treatment_ballot")
    fixture_input = copy.deepcopy(fixture)

    sampler_bot = bot_factory()
    sampler_snapshot = _snapshot_bot(sampler_bot, seed=seed, label="sampler bot")
    root, worlds, tape_receipt = sample_public_refusal_tape(
        sampler_bot, fixture_input, mode=mode, seed=seed,
        fill_seed=fill_seed, check_budget=check_budget)
    if root.turn != fixture_input.seat:
        raise ValueError("sampled root is not at fixture seat")

    legal = enumerate_legal(root, fixture_input.seat,
                            cap=sampler_bot.config.cap)
    if not legal.complete or type(legal.count) is not int or legal.count < 1:
        raise ValueError("complete legal action pool is required")
    if expected_legal_count is not None and legal.count != expected_legal_count:
        raise ValueError("legal count differs from declared panel plan")
    actions = copy.deepcopy(legal.actions)
    action_set = set(_canonical_collection(actions, "legal actions"))
    if not set(control) <= action_set or not set(treatment) <= action_set:
        raise ValueError("ballot member absent from complete legal pool")

    scoring_bots = []
    scoring_rng_states = []

    def scoring_factory():
        bot = bot_factory()
        if bot is sampler_bot or any(bot is prior for prior in scoring_bots):
            raise ValueError("sampler/scoring bot object reuse is forbidden")
        snapshot = _snapshot_bot(bot, seed=seed, label="scoring bot")
        if snapshot != sampler_snapshot:
            raise ValueError("scoring bot recipe/checkpoint drifted from sampler")
        scoring_bots.append(bot)
        scoring_rng_states.append(bot.sampler.rng.getstate())
        return bot

    if mode == "fresh-root":
        collection = collect_fixed_tape_panel(
            scoring_factory, root, fixture_input.seat, actions,
            control_input, treatment_input, worlds, check_budget=check_budget)
    else:
        collection = collect_history_primed_panel(
            scoring_factory, root, fixture_input.seat, actions,
            control_input, treatment_input, worlds, check_budget=check_budget)
    if any(bot.sampler.rng.getstate() != state
           for bot, state in zip(scoring_bots, scoring_rng_states)):
        raise ValueError("scoring bot sampler RNG was consumed")

    return {
        "schema": "public-fixture-panel-v1",
        "fixture_id": fixture_input.id,
        "mode": mode,
        "seed": seed,
        "fill_seed": fill_seed,
        "config": sampler_snapshot["config"],
        "checkpoint_sha256": sampler_snapshot["checkpoint_sha256"],
        "effective": sampler_snapshot["effective"],
        "legal_count": legal.count,
        "actions": actions,
        "tape_receipt": tape_receipt,
        "worlds": worlds,
        "collection": collection,
        "provenance_verified": False,
        "model_verified": False,
        "serving_choice_assessed": False,
    }


__all__ = ["collect_public_fixture_panel"]
