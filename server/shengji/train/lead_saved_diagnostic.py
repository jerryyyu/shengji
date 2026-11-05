"""Consume a saved validated readout for a fixed, bounded lead diagnosis.

No raw duel files are opened. The caller owns input identity, the hard process
watchdog and authorization. Fresh seeded decisions are not historical RNG replay.
"""
import copy

from .lead_counterfactual import compare_lead_actions
from .lead_saved_case import reconstruct_saved_lead
from .lead_root_capture import fingerprint, normalized


def diagnose_saved_leads(saved, cases, build_bot, *, gate):
    """Compare at most three named roots, requiring identical mirror states.

    A case supplies seed, play_index, seat and one to four alternative actions.
    build_bot(seed) must return the reviewed served recipe. Returned evidence
    distinguishes admission and repricing; it cannot identify horizon error.
    """
    if not 1 <= len(cases) <= 3:
        raise ValueError('supply one to three cases')
    keys = [(c['seed'], c['play_index'], c['seat']) for c in cases]
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate case')
    prepared = []
    for case in cases:
        gate()
        rows = [r for r in saved['validated_rows'] if r['seed'] == case['seed']]
        if len(rows) != 2 or {r['mirror'] for r in rows} != {0, 1}:
            raise ValueError('case requires exactly two mirrors')
        rows.sort(key=lambda r: r['mirror'])
        roots = [reconstruct_saved_lead(r, case['play_index'], case['seat']) for r in rows]
        if (fingerprint(roots[0][0]) != fingerprint(roots[1][0])
                or normalized(vars(roots[0][1])) != normalized(vars(roots[1][1]))):
            raise ValueError('mirror root or refusal state drift')
        prepared.append((case, *roots[0]))
    results = []
    for case, root, ledger in prepared:
        gate()
        bot = build_bot(case['seed'])
        if bot.refusal_event_complete:
            raise ValueError('requires own-turn refusal observation recipe')
        bot._refusals = copy.deepcopy(ledger)
        evidence = compare_lead_actions(bot, root, case['seat'], case['alternatives'], gate=gate)
        results.append(dict(case=copy.deepcopy(case), evidence=evidence))
    gate()
    return dict(schema='saved-lead-diagnostic-v1', cases=results,
                claim='Fresh common-world repricing with reconstructed own-turn refusal history; not historical sampling cadence, RNG, regret, horizon attribution or strength.')
