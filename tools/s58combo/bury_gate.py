"""Pure bury receipt checks extracted from the established v103s58 reader.

Source: ~/.claude/jobs/68f9c8bd/tmp/fl-pilot/v103s58/v103s58_reader/v103s58_reader.py
"""
import math
import validity
from declaration_gate import valid_declaration


def check_optional_stages(plan, shards):
    """Require banker-linked bury coverage and symmetric optional-stage ceilings."""
    counts = {side: dict(buries=0, bury_fallback=0, declares=0, declare_abandon=0)
              for side in ('candidate', 'comparator')}
    reasons = []
    for window in plan['windows']:
        side = window['side']
        for shard in shards[window['output']]:
            expected, seen = set(), set()
            for row in shard['records']:
                mirror, banker = row.get('mirror'), row.get('banker')
                if type(mirror) is not int or mirror not in (0, 1) or type(banker) is not int or not 0 <= banker < 4:
                    reasons.append(f'{side}: malformed banker witness')
                elif banker % 2 == mirror:
                    expected.add((mirror, banker))
            for trace in shard['decision_traces']:
                if trace.get('side') != 'arm':
                    continue
                buries = trace.get('bury_decisions')
                if not isinstance(buries, list):
                    reasons.append(f'{side}: missing bury trace')
                    continue
                for rec in buries:
                    try:
                        valid = _bury_valid(rec) and bury_chooser(rec) == 'wide'
                        key = (trace.get('mirror'), rec.get('seat')) if isinstance(rec, dict) else None
                        valid = valid and type(rec.get('seat')) is int and key in expected and key not in seen
                    except (TypeError, ValueError, KeyError):
                        valid = False
                    if not valid:
                        reasons.append(f'{side}: malformed, unexpected or duplicate bury receipt')
                        continue
                    seen.add(key)
                    counts[side]['buries'] += 1
                    counts[side]['bury_fallback'] += int(rec['schema'] == 'cwv-bury-fallback-v1')
                for rec in trace.get('declare_decisions', []):
                    if not valid_declaration(rec):
                        reasons.append(f'{side}: malformed declaration receipt')
                        continue
                    counts[side]['declares'] += 1
                    counts[side]['declare_abandon'] += int(not rec['evaluated'])
            if seen != expected:
                reasons.append(f'{side}: incomplete banker bury coverage')
    ceilings = dict(bury_fallback=.01, declare_abandon=.01)
    faults = validity.arm_fault_ceilings(counts, ceilings, arms=tuple(counts), tier='SCREEN')
    coverage = dict(check='optional_stage_coverage', verdict='SCREEN_INVALID' if reasons else 'VALID', reasons=reasons)
    return dict(validity.combine([coverage, faults], tier='SCREEN'), counts=counts, ceilings=ceilings)

LEAF_PLAYERS = ('heuristic', 'policy')

BURY_WIDE_K = dict(candidate=64, comparator=64)

BURY_WIDE_K_MAX = 128

def _nonneg_int(value):
    return type(value) is int and value >= 0

def _leaf_valid(rec):
    (leaf, fallbacks) = (rec.get('leaf_first_trick'), rec.get('leaf_first_trick_fallbacks'))
    return type(leaf) is str and leaf in LEAF_PLAYERS and _nonneg_int(fallbacks) and (leaf == 'policy' or fallbacks == 0)

BURY_SCHEMAS = ('cwv-bury-policy-v1', 'cwv-bury-fallback-v1')

BURY_REASONS = {None: 'none', 'budget': 'budget', 'search-error': 'search_error'}

BURY_STAGES = ('completed', 'pre_enumeration', 'pre_scoring', 'post_scoring')

BURY_CHOOSERS = ('wide', 'hybrid')

WIDE_VALUE_KEYS = ('candidates', 'worlds', 'chosen_index', 'chosen_is_incumbent', 'seconds', 'k')

def _int(value, low=0):
    return type(value) is int and value >= low

def bury_stage(rec):
    (cc, mp) = (rec.get('candidate_count', 'absent'), rec.get('model_positions', 'absent'))
    if rec['schema'] == BURY_SCHEMAS[0]:
        return 'completed' if _int(cc, 1) and _int(mp, 1) else None
    if cc is None:
        return 'pre_enumeration' if _int(mp) and mp == 0 else None
    if not _int(cc, 1):
        return None
    if mp is None or (_int(mp) and mp == 0):
        return 'pre_scoring'
    return 'post_scoring' if _int(mp, 1) else None

def bury_chooser(rec):
    (fc, mcr) = (rec.get('finalist_count', 'absent'), rec.get('mc_rollouts', 'absent'))
    if rec['schema'] == BURY_SCHEMAS[0]:
        sw = rec.get('selection_worlds', 'absent')
        if _int(fc) and fc == 0 and _int(mcr) and (mcr == 0) and ('mc_evidence' in rec) and (rec['mc_evidence'] is None) and _int(sw) and (sw == 0) and (rec.get('shortlist') == [0]) and (type(rec.get('rollout_seconds')) is float) and (rec['rollout_seconds'] == 0.0):
            return 'wide'
        if _int(fc, 1) and _int(mcr, 1) and _int(sw, 1) and ('mc_evidence' not in rec) and (rec.get('shortlist__len') == fc):
            return 'hybrid'
        return None
    if _int(fc) and fc == 0 and _int(mcr) and (mcr == 0):
        return 'wide'
    if fc is None and 'finalist_count' in rec or (_int(fc, 1) and bury_stage(rec) == 'post_scoring'):
        return 'hybrid' if _int(mcr) else None
    return None

def _wide_value_ok(rec):
    wv = rec['wide_value']
    if not isinstance(wv, dict) or not all((k in wv for k in WIDE_VALUE_KEYS)):
        return False
    (s, k) = (wv['seconds'], wv['k'])
    if type(k) is not int or k != BURY_WIDE_K['candidate'] or k != BURY_WIDE_K['comparator'] or ('swaps' in wv) or ('two_swap_count' in wv):
        return False
    return wv['candidates'] == rec['candidate_count'] <= k and wv['chosen_index'] == rec['picked_index'] and (type(wv['chosen_is_incumbent']) is bool) and (wv['chosen_is_incumbent'] == (rec['picked_index'] == 0)) and (wv['worlds'] == rec.get('model_worlds')) and (type(s) in (int, float)) and math.isfinite(s) and (s >= 0)

def _bury_valid(rec):
    if not isinstance(rec, dict) or rec.get('schema') not in BURY_SCHEMAS:
        return False
    (seconds, reason) = (rec.get('elapsed_seconds'), rec.get('fallback_reason', 'absent'))
    if not (type(seconds) in (int, float) and math.isfinite(seconds) and (seconds >= 0) and ('fallback_reason' in rec) and (reason is None or (type(reason) is str and reason in BURY_REASONS)) and ((reason is None) == (rec['schema'] == BURY_SCHEMAS[0])) and _leaf_valid(rec) and ('candidate_count' in rec) and ('model_positions' in rec)):
        return False
    (stage, chooser) = (bury_stage(rec), bury_chooser(rec))
    if stage is None or chooser is None:
        return False
    if chooser == 'wide' and rec['candidate_count'] is not None and (rec['candidate_count'] > BURY_WIDE_K_MAX):
        return False
    if stage == 'completed':
        (cc, worlds, picked) = (rec['candidate_count'], rec.get('model_worlds'), rec.get('picked_index'))
        if not (rec.get('candidates__len') == cc and rec.get('model_means__len') == cc and _int(worlds, 1) and (rec['model_positions'] == cc * worlds) and _int(picked) and (picked < cc)):
            return False
    if 'wide_value' in rec:
        return stage == 'completed' and chooser == 'wide' and _wide_value_ok(rec)
    return True
