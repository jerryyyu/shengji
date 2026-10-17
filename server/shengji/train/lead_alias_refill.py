"""Bounded lead admission refill using sampled-world execution signatures."""

import math
import time
from types import SimpleNamespace

from shengji.harvest.legal import resolve_lead
from shengji.train.optional_stage import OptionalStage

MAX_ACTIONS = 64
MAX_SECONDS = 0.05


def execution_signature(rnd, seat, action, worlds, check_budget):
    parts = []
    for hands, _ in worlds:
        check_budget()
        parts.append(tuple(sorted(resolve_lead(rnd, seat, action, hands)[0])))
    return tuple(parts)


def refill_indices(rnd, seat, actions, preferences, chosen, worlds, check_budget=None):
    """Preserve the anchor/width; publish only a complete, bounded refill.

    Signatures compare engine-accepted cards in every original sampled world.
    They establish execution aliases, not equivalent public information after
    a refused throw. The normal value and selection rules still choose a play.
    """
    from shengji.train.pv_search_policy import PVSearchBudgetExceeded

    original = list(chosen)
    record = {"lead_alias_refill_applied": False, "lead_alias_refill_alias_slots": 0,
              "lead_alias_refill_replacements": 0, "lead_alias_refill_examined": 0}
    if not worlds or len(original) < 2 or rnd.trick is None or rnd.trick.plays:
        return original, record
    if len(original) > MAX_ACTIONS:
        return original, {**record, "lead_alias_refill_skipped": "ballot_cap"}
    cache = {}
    stage = OptionalStage(SimpleNamespace(), (), hard_check=check_budget,
                          budget_errors=PVSearchBudgetExceeded,
                          soft_deadline=time.perf_counter() + MAX_SECONDS,
                          clock=time.perf_counter, soft_error=PVSearchBudgetExceeded,
                          abandon_on=PVSearchBudgetExceeded)
    retained, duplicates, seen = [], [], set()

    def signature(index):
        if index not in cache:
            cache[index] = execution_signature(rnd, seat, actions[index], worlds,
                                               check_budget=stage.guard)
        return cache[index]

    with stage:
        for index in original:
            sig = signature(index)
            if sig in seen:
                duplicates.append(index)
            else:
                retained.append(index)
                seen.add(sig)
        ranked = (sorted(range(len(actions)), key=lambda i: (-preferences[i], i))
                  if duplicates else ())
        for index in ranked:
            if len(retained) == len(original) or len(cache) >= MAX_ACTIONS:
                break
            if not math.isfinite(preferences[index]) or index in cache:
                continue
            sig = signature(index)
            if sig not in seen:
                retained.append(index)
                seen.add(sig)
        replacements = len(retained) - (len(original) - len(duplicates))
        retained.extend(duplicates[:len(original) - len(retained)])
        if not replacements:
            retained = original
        stage.publish(changed=retained != original)
    if stage.abandoned:
        return original, {**record, "lead_alias_refill_abandoned": stage.reason,
                          "lead_alias_refill_error": stage.error,
                          "lead_alias_refill_examined": len(cache)}
    return retained, {**record, "lead_alias_refill_applied": retained != original,
                      "lead_alias_refill_alias_slots": len(duplicates),
                      "lead_alias_refill_replacements": replacements,
                      "lead_alias_refill_examined": len(cache)}
