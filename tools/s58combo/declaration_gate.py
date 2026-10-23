"""Validate the value-declare receipts that the producer actually publishes."""
import math


def valid_declaration(rec):
    """Missing gated calls require separate coverage evidence, not invented zeros."""
    if not isinstance(rec, dict) or rec.get('schema') != 'pv-value-declare-decision-v1':
        return False
    if any(type(rec.get(k)) is not bool for k in ('evaluated', 'changed', 'final')):
        return False
    reason = rec.get('fallback_reason', 'absent')
    seconds = rec.get('seconds')
    worlds, done = rec.get('worlds'), rec.get('worlds_completed')
    leaf, fallbacks = rec.get('leaf_first_trick'), rec.get('leaf_first_trick_fallbacks')
    cards, played, heuristic = rec.get('cards_dealt'), rec.get('played'), rec.get('heuristic')
    return (
        (reason is None or type(reason) is str and reason in ('hard_budget', 'error'))
        and rec['evaluated'] == (reason is None)
        and (rec['evaluated'] or not rec['changed'])
        and type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0
        and type(worlds) is int and worlds > 0
        and type(done) is int and 0 <= done <= worlds
        and type(leaf) is str and leaf in ('heuristic', 'policy')
        and type(fallbacks) is int and fallbacks >= 0
        and (leaf == 'policy' or fallbacks == 0)
        and type(cards) is int and 0 <= cards <= 100
        and type(played) is str and type(heuristic) is str
        and rec['changed'] == (played != heuristic)
    )
