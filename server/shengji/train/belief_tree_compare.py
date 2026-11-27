"""Compare a replayed lead on the same production ballot and outer worlds."""
from dataclasses import dataclass

import numpy as np

from ..ai.refusal import RefusalLedger
from .belief_tree_replay import TrancheRoot


@dataclass(frozen=True)
class PairedLeadValues:
    """The base pass's action order, exact flat means and the tree's world rows."""

    actions: tuple[tuple[str, ...], ...]
    flat_means: np.ndarray
    reply_values: np.ndarray

    def contrast(self, true_deal_values):
        """Compare first-argmax picks to independently supplied (served, heuristic) finishes.

        Every action is keyed by its sorted cards so a yardstick's evaluation order
        cannot change the result. Both columns are signed levels for the root team.
        """
        keys = [tuple(sorted(action)) for action in self.actions]
        if (len(keys) < 2 or len(set(keys)) != len(keys) or set(keys) != set(true_deal_values)
                or self.flat_means.shape != (len(keys),) or self.reply_values.shape != (64, len(keys))):
            raise ValueError("paired values and true-deal yardsticks must cover the same complete ballot")
        values = np.asarray([true_deal_values[key] for key in keys], dtype=np.float64)
        if (values.shape != (len(keys), 2) or not np.isfinite(values).all()
                or not np.isfinite(self.flat_means).all() or not np.isfinite(self.reply_values).all()):
            raise ValueError("expected finite paired estimates and two true-deal values per action")
        flat = int(np.argmax(self.flat_means))
        tree = int(np.argmax(self.reply_values.mean(axis=0)))
        sf, vt = values[tree] - values[flat]
        return {"flat_action": keys[flat], "tree_action": keys[tree],
                "flat_all_tied": bool(np.all(self.flat_means == self.flat_means[0])),
                "sf_gain": float(sf), "vt_gain": float(vt), "sf_regret_change": float(-sf)}


class _BasePassComplete(Exception):
    """Stop at the flat estimator boundary before final selection rules."""


def compare_replayed_lead(root: TrancheRoot, flat_bot, *, seed: int, depth_worlds: int,
                          reply_cap: int, batch_size: int, reply_value_weight: float) -> PairedLeadValues:
    """Compare the actual W64/K8 base estimator with one offline reply ply.

    The caller supplies a dedicated bot with the pinned unified slots and lifted
    decision and leaf deadlines. Production search handles the draw, admission,
    framing and accumulation. The comparison uses its base means before
    selection, exact search or confirmation. The bot is consumed by this probe.
    """
    rnd = root.round
    if rnd.phase != "play" or rnd.trick is None or rnd.trick.plays or rnd.turn != root.target.seat:
        raise ValueError("comparison requires the replayed lead and actor")
    if (flat_bot.worlds != 64 or flat_bot.candidates != 8 or flat_bot.adaptive_k
            or flat_bot.wide_lead_admission or flat_bot.adaptive_worlds
            or flat_bot.adaptive_worlds_leads or flat_bot.two_trick_lead):
        raise ValueError("comparison requires the fixed W64/K8 flat estimator")
    if flat_bot.serving_budget_seconds is not None or flat_bot.leaf_greedy_deadline_ms:
        raise ValueError("comparison requires lifted search and leaf deadlines")
    model = getattr(flat_bot, "unified_value_model", None)
    belief = flat_bot.belief_model
    if (model is None or getattr(flat_bot, "unified_prior_model", None) is not model
            or getattr(flat_bot, "unified_reply_model", None) is not model
            or getattr(belief, "unified", None) is not model or not flat_bot.refusal_constraints):
        raise ValueError("comparison requires one unified model and the replay refusal ledger")

    # Seed both arms with the same recorded refusals, including ones whose
    # notices have expired. Do not retain the replay's ledger on the bot.
    ledger = RefusalLedger()
    ledger.key = tuple(rnd.deck)
    ledger.refusals = list(root.refusals)
    previous_ledger = flat_bot._refusals
    had_override = "_value_means" in vars(flat_bot)
    previous_override = vars(flat_bot).get("_value_means")
    estimate = flat_bot._value_means
    captured = None

    def base_pass(position, seat, actions, worlds, check_budget=None):
        nonlocal captured
        if position is not rnd or seat != rnd.turn or len(worlds) != 64 or len(actions) < 2:
            raise ValueError("missing complete paired root ballot and 64 worlds")
        if flat_bot._draw_tally_record().get("belief_fallback_all_draws") != 0:
            raise ValueError("flat belief draw fell back or did not report its validity")
        if tuple(flat_bot._refusals.refusals) != root.refusals:
            raise ValueError("flat comparison read a different refusal ledger")
        frame = flat_bot.unified_frame
        if frame is None or frame.rnd is not rnd or frame.seat != seat:
            raise ValueError("flat estimator did not run in its unified decision frame")
        value_rows = flat_bot.unified_value_rows
        value_other = flat_bot.unified_value_other
        reply_served = flat_bot.unified_reply_served
        means, batches = estimate(position, seat, actions, worlds, check_budget)
        means = np.asarray(means, dtype=np.float64)
        if (batches < 1 or means.shape != (len(actions),) or not np.isfinite(means).all()
                or flat_bot.unified_value_rows <= value_rows or flat_bot.unified_value_other != value_other
                or flat_bot.unified_reply_served != reply_served):
            raise ValueError("flat estimator did not complete unified scoring")
        ballot = tuple(tuple(cards) for cards in actions)
        tape = tuple((tuple(tuple(hand) for hand in hands), tuple(buried)) for hands, buried in worlds)
        captured = ballot, tape, means
        raise _BasePassComplete

    flat_bot._refusals = ledger
    flat_bot._value_means = base_pass
    try:
        flat_bot.decide_play(rnd, rnd.turn)
    except _BasePassComplete:
        pass
    finally:
        flat_bot._refusals = previous_ledger
        if had_override:
            flat_bot._value_means = previous_override
        else:
            del flat_bot._value_means
    if captured is None:
        raise ValueError("flat search did not price its base ballot")
    actions, worlds, means = captured
    reply_values = root.backup(actions, worlds, model=model, belief=belief, seed=seed,
                               depth_worlds=depth_worlds, reply_cap=reply_cap, batch_size=batch_size,
                               reply_value_weight=reply_value_weight)
    if reply_values.shape != (64, len(actions)) or not np.isfinite(reply_values).all():
        raise ValueError("reply estimator did not complete the paired ballot")
    return PairedLeadValues(actions, means, reply_values)
