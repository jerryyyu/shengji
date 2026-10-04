"""One-shot diagnostic sampling on a reconstructed public refusal root.

This helper binds the existing public ledger reconstruction to one canonical
PV sampler call. It reconstructs the declared ledger mode, but does not verify
the fixture's historical provenance or authenticate the checkpoint. Canonical
refusal sampling can fall back to plain worlds; the receipt preserves those
counts. It never invokes prediction, scoring, or serving selection. A
real sampler call is still scientific collection and requires the external
reviewed packet and authorization.
"""

from __future__ import annotations

import copy
import random
import re

from .public_refusal_history import public_root_with_ledger


_CONSUMED = "_public_refusal_tape_consumed"


def _require_fresh_bot(bot, seed: int):
    from ..ai.mcbot import MCBot
    from ..train.pv_search_policy import PVSearchBot

    if not isinstance(bot, PVSearchBot):
        raise ValueError("a dedicated PVSearchBot is required")
    if getattr(getattr(bot, "_worlds", None), "__func__", None) is not PVSearchBot._worlds:
        raise ValueError("canonical PVSearchBot._worlds implementation is required")
    config = getattr(bot, "config", None)
    if config is None or getattr(config, "refusal_constraints", None) is not True:
        raise ValueError("refusal_constraints must be enabled in bot config")
    if getattr(bot, "refusal_constraints", None) is not True:
        raise ValueError("refusal_constraints must be enabled on bot")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    sampler = getattr(bot, "sampler", None)
    if type(sampler) is not MCBot:
        raise ValueError("canonical MCBot sampler is required")
    for name in ("_sample_hands", "_complete_determinized_hands"):
        if (getattr(getattr(sampler, name, None), "__func__", None)
                is not getattr(MCBot, name)):
            raise ValueError(f"canonical MCBot.{name} implementation is required")
    if (type(getattr(bot, "seed", None)) is not int
            or bot.seed != seed
            or type(getattr(sampler, "seed", None)) is not int
            or sampler.seed != seed):
        raise ValueError("bot and sampler seeds must match requested seed")
    rng = getattr(sampler, "rng", None)
    if type(rng) is not random.Random or rng.getstate() != random.Random(seed).getstate():
        raise ValueError("sampler RNG is stale")
    if getattr(bot, _CONSUMED, False):
        raise ValueError("public refusal tape sampler already consumed")
    ledger = getattr(bot, "_refusals", None)
    if ledger is None or getattr(ledger, "key", object()) is not None \
            or getattr(ledger, "refusals", object()) != []:
        raise ValueError("bot refusal ledger must be pristine")
    worlds = getattr(config, "worlds", None)
    if type(worlds) is not int or worlds < 1:
        raise ValueError("config.worlds must be a positive integer")
    if type(getattr(bot, "worlds", None)) is not int or bot.worlds != worlds:
        raise ValueError("bot worlds must match config.worlds")
    checkpoint = getattr(bot, "checkpoint_sha256", None)
    declared = getattr(config, "checkpoint_sha256", None)
    if (type(checkpoint) is not str or not re.fullmatch(r"[0-9a-f]{64}", checkpoint)
            or checkpoint != declared):
        raise ValueError("declared checkpoint hash must match config and be lowercase hex")
    return config, worlds, checkpoint


def sample_public_refusal_tape(bot, fixture, *, mode, seed, fill_seed=0,
                               check_budget=None):
    """Sample exactly one declared-mode tape through canonical PV code.

    ``mode`` is passed explicitly to :func:`public_root_with_ledger`; neither
    mode nor the returned ledger proves how the caller sourced the fixture.
    The bot is one-shot: a sampler failure consumes it just as a success does.
    """
    if mode not in ("fresh-root", "history-primed"):
        raise ValueError("explicit fresh-root or history-primed mode required")
    if type(fill_seed) is not int or fill_seed < 0:
        raise ValueError("fill_seed must be a nonnegative integer")
    _config, expected_worlds, checkpoint = _require_fresh_bot(bot, seed)

    root, ledger, mode_receipt = public_root_with_ledger(
        fixture, mode=mode, fill_seed=fill_seed)
    if not isinstance(mode_receipt, dict) or mode_receipt.get("mode") != mode:
        raise ValueError("public root receipt does not match requested mode")
    if getattr(ledger, "key", None) != tuple(root.deck):
        raise ValueError("public ledger is not bound to returned root deck")
    bot._refusals = ledger

    # Mark immediately before dispatch.  Any exception from the sampler makes
    # this bot unusable for a retry, including budget or sentinel failures.
    setattr(bot, _CONSUMED, True)
    worlds, attempts = bot._worlds(root, fixture.seat, check_budget)
    if type(worlds) is not list or len(worlds) != expected_worlds:
        raise ValueError("canonical sampler returned the wrong world count")
    if type(attempts) is not int or attempts < expected_worlds:
        raise ValueError("canonical sampler returned invalid attempts")
    stats = getattr(bot, "_last_sampling", None)
    if not isinstance(stats, dict):
        raise ValueError("canonical sampler statistics are missing")

    receipt = {
        "schema": "public-refusal-tape-v1",
        "ledger_receipt": copy.deepcopy(mode_receipt),
        "mode": mode,
        "seed": seed,
        "fill_seed": fill_seed,
        "world_count": expected_worlds,
        "attempts": attempts,
        "last_sampling": copy.deepcopy(stats),
        "sampler_record": copy.deepcopy(bot._sampler_record()),
        "checkpoint_sha256": checkpoint,
        "checkpoint_hash_verified": False,
        "provenance_verified": False,
        "model_verified": False,
        "live_rng_state_reconstructed": False,
    }
    return root, worlds, receipt


__all__ = ["sample_public_refusal_tape"]
