"""Engine-outcome checks before the in-memory paired estimator; no raw IO."""
from admission import admit_records
from paired_result import paired_result
from decision_gate import check_decisions
from exact_gate import check_exact
from bury_gate import check_optional_stages
from greedy_gate import check_greedy
import validity


def check_outcomes(records):
    required = ('banker', 'attacker_points', 'winner_team', 'level_change')
    rows = [(f'{output}:{i}', row) for output, values in records.items()
            for i, row in enumerate(values)]
    checks = [validity.outcome_consistency(rows, tier='SCREEN', require=required)]
    reasons = []
    for where, row in rows:
        fields = (*required, 'mirror', 'arm_team', 'arm_won', 'arm_utility', 'baseline_utility')
        if any(type(row.get(k)) is not int for k in fields):
            reasons.append(f'{where}: missing or non-integer outcome field')
            continue
        banker, points = row['banker'], row['attacker_points']
        if not 0 <= banker <= 3 or points < 0 or points % 5 or row['mirror'] not in (0, 1):
            reasons.append(f'{where}: invalid banker, points or mirror')
            continue
        winner, change = validity.engine_level_outcome(points, banker)
        won = int(winner == row['mirror'])
        utility = max(1, change) * (1 if won else -1)
        expected = dict(winner_team=winner, level_change=change, arm_team=row['mirror'],
                        arm_won=won, arm_utility=utility, baseline_utility=-utility)
        if any(row[k] != value for k, value in expected.items()):
            reasons.append(f'{where}: outcome or utility disagrees with engine/seat mirror')
    checks.append(dict(check='engine_and_signed_utility',
                       verdict='SCREEN_INVALID' if reasons else 'VALID', reasons=reasons[:20]))
    return validity.combine(checks, tier='SCREEN')


def outcome_checked_result(plan, expected_configs, configs, shards):
    """Reject impossible outcomes before estimation, after recipe admission.

    The caller still owes sealed-input binding and the remaining stage gates.
    Passing these checks alone is not a valid-screen verdict.
    """
    records = admit_records(plan, expected_configs, configs, shards)
    outcome_check = check_outcomes(records)
    if outcome_check['verdict'] != 'VALID':
        return dict(status='OUTCOME_INVALID', outcome_check=outcome_check)
    decision_check = check_decisions(plan, shards)
    if decision_check['verdict'] != 'VALID':
        return dict(status='DECISION_INVALID', outcome_check=outcome_check, decision_check=decision_check)
    exact_check = check_exact(plan, shards)
    if exact_check['verdict'] != 'VALID':
        return dict(status='EXACT_INVALID', exact_check=exact_check)
    optional_check = check_optional_stages(plan, shards)
    if optional_check['verdict'] != 'VALID':
        return dict(status='OPTIONAL_STAGE_INVALID', optional_check=optional_check)
    greedy_check = check_greedy(plan, shards)
    if greedy_check['verdict'] != 'VALID':
        return dict(status='GREEDY_INVALID', greedy_check=greedy_check)
    return dict(status='STAGE_OUTCOME_CHECKED_ONLY', outcome_check=outcome_check, decision_check=decision_check,
                exact_check=exact_check, optional_check=optional_check, greedy_check=greedy_check,
                pending=['sealed input binding', 'dtrx activation and remaining recipe-specific telemetry'],
                estimate=paired_result(plan['windows'], records))
