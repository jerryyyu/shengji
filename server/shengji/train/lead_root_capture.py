"""DEV collector adapter: JSON engine roots, not exact bot/RNG replay.

Start after bury, call committed after EVERY play, capture before the lead's
analysis mutates bot diagnostic state. Full hidden deal stays DEV-only; never
feed this payload directly to a policy. No inference or file IO in this module.
"""
import copy
import json
from collections import Counter
from dataclasses import asdict, is_dataclass
from contextlib import contextmanager

from shengji.harvest.rebuild import round_from_setup, setup_from_round
from shengji.ai.refusal import Refusal, RefusalLedger, on_record


# This hook is deliberately process-local.  It is a DEV collector facility,
# not a serving extension: a collector must own the single thread that runs
# the observed bot while the context is active.
# Follow and lead hooks patch process-global solver functions, so they share a
# guard even when their collectors are otherwise independent.
_EXACT_OBSERVERS = set()


def finish_eligible(rnd, seat):
    hand = rnd.hands[seat]
    return (rnd.phase == 'play' and not rnd.trick.plays and 2 <= len(hand) <= 8
            and len({rnd.ordering.eff_suit(c) for c in hand}) == 1)


@contextmanager
def observe_finish_pool(bot, rnd, seat):
    """Observe the actual returned legal pool; never rerun enumeration/inference.

    Unknown if the decision expires before returning a pool. This instrumentation
    is collector-only and neither changes the factory class nor supplies actions.
    """
    evidence = {'eligible': finish_eligible(rnd, seat), 'present': None}
    if not evidence['eligible'] or not hasattr(bot, '_legal'):
        yield evidence
        return
    hand = tuple(sorted(rnd.hands[seat]))
    original = bot._legal
    had_own = '_legal' in vars(bot)
    own = vars(bot).get('_legal')

    def observed(*args, **kwargs):
        result = original(*args, **kwargs)
        evidence.update(present=any(tuple(sorted(a)) == hand for a in result.actions),
                        complete=result.complete, count=result.count)
        return result

    bot._legal = observed
    try:
        yield evidence
    finally:
        if had_own:
            bot._legal = own
        else:
            del bot._legal


def classify_finish_lead(row):
    """Engine-only evidence, not counterfactual value or strength attribution.

    True-deal refusal is hindsight, not information available to the bot. Missing
    capture/admission fields remain unknown, including budget-fallback records.
    """
    from shengji.harvest.legal import forced_lead
    rnd, _ = restore_with_ledger(row['replay'])
    if rnd.phase != 'play' or rnd.trick.plays or rnd.turn != row['seat']:
        raise ValueError('not the captured lead turn')
    rec = row['replay'].get('decision') or {}
    attempted = row.get('attempted', rec.get('played'))
    if not attempted or (rec.get('played') is not None
                         and sorted(attempted) != sorted(rec['played'])):
        raise ValueError('attempted action drift')
    eligible = finish_eligible(rnd, rnd.turn)
    pool = row.get('finish_pool')
    if pool is not None and pool.get('eligible') != eligible:
        raise ValueError('finish eligibility drift')
    present = None if pool is None else pool.get('present')
    if present is not None and type(present) is not bool:
        raise ValueError('invalid pool presence')
    hand = sorted(rnd.hands[rnd.turn])
    admitted = (rec.get('admitted') if rec.get('schema') == 'pv-search-decision-v1'
                and rec.get('work_complete') is True else None)
    in_admitted = (any(sorted(a) == hand for a in admitted)
                   if eligible and isinstance(admitted, list) else None)
    if present is False and in_admitted is True:
        raise ValueError('admitted finish absent from captured pool')
    forced = forced_lead(rnd, rnd.turn, hand) if eligible else None
    return dict(eligible=eligible, hand_size=len(hand),
                decision_schema=rec.get('schema'), work_complete=rec.get('work_complete'),
                pool_present=present if eligible else None, admitted=in_admitted,
                whole_hand_played=sorted(attempted) == hand,
                whole_hand_refused_true_deal=(forced is not None) if eligible else None,
                forced_component=forced,
                ranking_or_horizon_error=None)


def normalized(obj):
    def default(value):
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, (set, frozenset)):
            return sorted(value)
        return vars(value)
    return json.loads(json.dumps(obj, default=default, sort_keys=True))


def _action_multiset(action):
    """Return an order-independent, JSON-safe key for a submitted action."""
    if not isinstance(action, list) or not action:
        raise ValueError('malformed admitted actions')
    try:
        counts = Counter(action)
    except TypeError as exc:
        raise ValueError('malformed admitted actions') from exc
    return tuple(sorted(counts.items()))


@contextmanager
def observe_exact_follow(bot, collector):
    """Capture the real optional exact-follow stage for one DEV bot call.

    ``PVSearchBot._search`` imports ``pv_exact_follow.rerank_follow`` at call
    time, so patching the module function here observes the actual serving
    consumer without changing the normal no-observer path.  The wrapper only
    records a call made by this bot's active ``_search`` invocation and with
    that invocation's root/seat; unrelated direct solver calls are ignored.

    This is intentionally single-threaded collector plumbing.  Nested
    observers are rejected, and the original instance method
    and module function are restored even when the search or solver raises.
    Captured rows describe the exact stage result, not the final played action:
    the outer optional-stage guard may still abandon that result.
    """
    if not hasattr(collector, 'capture_exact_stage'):
        raise TypeError('exact-follow collector must be LeadCapture-like')
    identity = id(bot)
    if _EXACT_OBSERVERS:
        raise RuntimeError('nested exact-follow observer')
    from . import pv_exact_follow

    original_rerank = pv_exact_follow.rerank_follow
    original_search = bot._search
    had_own_search = '_search' in vars(bot)
    saved_own_search = vars(bot).get('_search')
    active = []
    rows = []
    capture_failures = []

    def observed_search(rnd, seat, *args, **kwargs):
        active.append((rnd, seat))
        try:
            return original_search(rnd, seat, *args, **kwargs)
        finally:
            active.pop()

    def observed_rerank(rnd, seat, admitted, worlds, *, baseline_index=0,
                        max_hand_cards=4, max_nodes=250_000,
                        check_budget=None, solver='reference'):
        if not active or rnd is not active[-1][0] or seat != active[-1][1]:
            return original_rerank(
                rnd, seat, admitted, worlds, baseline_index=baseline_index,
                max_hand_cards=max_hand_cards, max_nodes=max_nodes,
                check_budget=check_budget, solver=solver)
        try:
            input_packet = collector.capture_exact_stage(
                rnd, ledger=bot._refusals, admitted=admitted, worlds=worlds,
                baseline_index=baseline_index)
        except Exception as exc:
            # The serving optional stage has a broad fallback for solver
            # failures.  Do not let it turn a collector defect into a silent
            # missing sample; re-raise the instrumentation failure after the
            # surrounding context has restored both patched functions.
            capture_failures.append(exc)
            input_packet = None
        row = {
            'schema': 'exact-follow-observation-dev-v1',
            'stage': 'result',
            'latency_evidence': False,
            'input': input_packet,
            'config': {
                'solver': solver,
                'max_hand_cards': max_hand_cards,
                'max_nodes': max_nodes,
            },
        }
        try:
            result = original_rerank(
                rnd, seat, admitted, worlds, baseline_index=baseline_index,
                max_hand_cards=max_hand_cards, max_nodes=max_nodes,
                check_budget=check_budget, solver=solver)
        except Exception as exc:
            row['result'] = {'exception': type(exc).__name__}
            rows.append(row)
            raise
        row['result'] = normalized(result)
        rows.append(row)
        return result

    _EXACT_OBSERVERS.add(identity)
    try:
        pv_exact_follow.rerank_follow = observed_rerank
        bot._search = observed_search
        yield rows
    finally:
        pv_exact_follow.rerank_follow = original_rerank
        if had_own_search:
            bot._search = saved_own_search
        else:
            del bot._search
        _EXACT_OBSERVERS.remove(identity)
        if capture_failures:
            raise capture_failures[0]


@contextmanager
def observe_exact_lead(bot, collector):
    """Capture the real bounded exact-lead solver calls made by one bot.

    The packet deliberately does not serialize the leaf continuation: replay
    requires the caller to provide the same callable explicitly.  Both shallow
    and deep solver seams are patched at their module boundary, and only calls
    from this bot's active root/seat are recorded.
    """
    if not hasattr(collector, 'capture_exact_stage'):
        raise TypeError('exact-lead collector must be LeadCapture-like')
    identity = id(bot)
    if _EXACT_OBSERVERS:
        raise RuntimeError('nested exact-lead observer')
    from . import pv_exact_deep, pv_exact_endgame

    original_deep = pv_exact_deep.exact_root_means
    original_shallow = pv_exact_endgame.exact_lead_means
    original_lead_decision = getattr(bot, '_exact_lead_decision', None)
    had_own_lead_decision = '_exact_lead_decision' in vars(bot)
    saved_own_lead_decision = vars(bot).get('_exact_lead_decision')
    lead_calls, rows, capture_failures = [], [], []

    def observed_lead_decision(rnd, seat, admitted, worlds, started,
                               check_budget, priors, base):
        lead_calls.append((rnd, seat, base))
        try:
            return original_lead_decision(
                rnd, seat, admitted, worlds, started, check_budget, priors, base)
        finally:
            lead_calls.pop()

    def capture_call(kind, rnd, seat, admitted, worlds, leaf_fn,
                     check_budget, max_nodes, max_hand_cards=None, level=None):
        if (not lead_calls or rnd is not lead_calls[-1][0]
                or seat != lead_calls[-1][1]):
            return None
        # base[2] is the actual finalized baseline candidate index; zero is not
        # generally the baseline after policy selection and is not replayable evidence.
        base = lead_calls[-1][2]
        try:
            packet = collector.capture_exact_stage(
                rnd, ledger=bot._refusals, admitted=admitted, worlds=worlds,
                baseline_index=base[2])
        except Exception as exc:
            capture_failures.append(exc)
            packet = None
        row = {
            'schema': 'exact-lead-observation-dev-v1', 'stage': 'result',
            'latency_evidence': False, 'input': packet,
            'leaf_fn_required_for_replay': True,
            'leaf_fn_source': 'caller-supplied',
            'exact_lead_policy_first': bool(getattr(bot, 'exact_lead_policy_first', False)),
            'baseline_played': normalized(base[3]),
            'config': {'solver': kind, 'max_nodes': max_nodes},
        }
        if max_hand_cards is not None:
            row['config']['max_hand_cards'] = max_hand_cards
        if level is not None:
            row['config']['level'] = level
        return row

    def observed_shallow(rnd, seat, admitted, worlds, leaf_fn, check_budget,
                         *, max_nodes=10_000):
        row = capture_call('shallow', rnd, seat, admitted, worlds, leaf_fn,
                           check_budget, max_nodes)
        try:
            result = original_shallow(rnd, seat, admitted, worlds, leaf_fn,
                                      check_budget, max_nodes=max_nodes)
        except Exception as exc:
            if row is not None:
                row['result'] = {'exception': type(exc).__name__}; rows.append(row)
            raise
        if row is not None:
            means, stats = result
            row['result'] = {'means': means.tolist(), 'stats': normalized(stats)}
            rows.append(row)
        return result

    def observed_deep(rnd, seat, admitted, worlds, leaf_fn, check_budget,
                      *, max_hand_cards, max_nodes, level=True):
        row = capture_call('deep', rnd, seat, admitted, worlds, leaf_fn,
                           check_budget, max_nodes, max_hand_cards, level)
        try:
            result = original_deep(rnd, seat, admitted, worlds, leaf_fn,
                                   check_budget, max_hand_cards=max_hand_cards,
                                   max_nodes=max_nodes, level=level)
        except Exception as exc:
            if row is not None:
                row['result'] = {'exception': type(exc).__name__}; rows.append(row)
            raise
        if row is not None:
            means, stats = result
            row['result'] = {'means': means.tolist(), 'stats': normalized(stats)}
            rows.append(row)
        return result

    _EXACT_OBSERVERS.add(identity)
    try:
        pv_exact_deep.exact_root_means = observed_deep
        pv_exact_endgame.exact_lead_means = observed_shallow
        if original_lead_decision is not None:
            bot._exact_lead_decision = observed_lead_decision
        yield rows
    finally:
        pv_exact_deep.exact_root_means = original_deep
        pv_exact_endgame.exact_lead_means = original_shallow
        if original_lead_decision is not None:
            if had_own_lead_decision:
                bot._exact_lead_decision = saved_own_lead_decision
            else:
                del bot._exact_lead_decision
        _EXACT_OBSERVERS.remove(identity)
        if capture_failures:
            raise capture_failures[0]


def replay_exact_lead(row, leaf_fn, *, policy_first=False):
    """Verify a complete captured result using its explicit leaf continuation.

    Collection rows must also report a completed published lead stage. Bare
    observer rows verify only the solver result, not final action publication.
    Policy-first replay requires an explicit caller assertion of that mode;
    result equality does not authenticate the callable or its provenance.
    """
    if not callable(leaf_fn):
        raise TypeError('replay requires a callable leaf_fn')
    if row.get('schema') != 'exact-lead-observation-dev-v1':
        raise ValueError('unknown exact-lead observation schema')
    expected = row.get('result')
    if (not isinstance(expected, dict) or set(expected) != {'means', 'stats'}
            or not isinstance(expected['means'], list) or not expected['means']
            or not isinstance(expected['stats'], dict)):
        raise ValueError('exact-lead replay requires a complete recorded result')
    if type(policy_first) is not bool or row.get('exact_lead_policy_first') is not policy_first:
        raise ValueError('exact-lead replay leaf mode mismatch')
    if 'decision' in row:
        decision = row['decision']
        if (not isinstance(decision, dict) or decision.get('work_complete') is not True
                or decision.get('exact_lead_status') != 'complete'
                or row.get('exact_lead_status') != 'complete'):
            raise ValueError('exact-lead collection stage was not published complete')
    packet = row.get('input')
    if not isinstance(packet, dict):
        raise ValueError('exact-lead observation has no replay input')
    rnd, _ledger, admitted, worlds, _baseline, _actual = restore_exact_stage(packet)
    config = dict(row.get('config') or {})
    solver = config.pop('solver', None)
    if 'max_nodes' not in config:
        raise ValueError('exact-lead replay config missing max_nodes')
    max_nodes = config.pop('max_nodes')
    if solver == 'shallow':
        if config:
            raise ValueError('unexpected exact-lead replay config')
        from .pv_exact_endgame import exact_lead_means
        means, stats = exact_lead_means(rnd, packet['seat'], admitted, worlds,
                                        leaf_fn, None, max_nodes=max_nodes)
    elif solver == 'deep':
        if set(config) - {'max_hand_cards', 'level'} or 'max_hand_cards' not in config:
            raise ValueError('unexpected exact-lead replay config')
        from .pv_exact_deep import exact_root_means
        means, stats = exact_root_means(
            rnd, packet['seat'], admitted, worlds, leaf_fn, None,
            max_hand_cards=config.pop('max_hand_cards'), max_nodes=max_nodes,
            level=config.pop('level', True))
    else:
        raise ValueError('unknown exact-lead solver')
    if config:
        raise ValueError('unexpected exact-lead replay config')
    if {'means': means.tolist(), 'stats': normalized(stats)} != expected:
        raise ValueError('exact-lead replay result mismatch')
    return means, stats


def evaluate_follow_prefix(row, *, budget_seconds, min_worlds=16,
                           time_scale=1.0, clock=None, true_deal=False):
    """DEV full-world benchmark and completed-prefix budget simulation.

    This runs every world without a serving deadline, then simulates a prefix.
    It is not a bounded serving implementation or proof of hard-budget safety.
    The caller supplies the remaining stage budget and any measured host scale;
    root restoration, earlier decision work and runtime contention are excluded.
    Only published collection rows are accepted. They are conditioned on reaching
    the solver, so this function cannot supply the eligibility denominator.
    """
    import math
    import time
    from .pv_exact_follow import rerank_follow, ExactFollowResult

    if type(true_deal) is not bool:
        raise ValueError('true_deal must be a bool')
    for name, value in [('budget_seconds', budget_seconds), ('time_scale', time_scale)]:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be positive and finite')
    if type(min_worlds) is not int or min_worlds < 1:
        raise ValueError('min_worlds must be a positive integer')
    if row.get('schema') != 'exact-follow-observation-dev-v1':
        raise ValueError('expected exact-follow observation')
    decision = row.get('decision')
    if (not isinstance(decision, dict) or decision.get('work_complete') is not True
            or decision.get('exact_follow_attempted') is not True
            or decision.get('exact_follow_abandoned') is not None
            or decision.get('exact_follow_error') is not None):
        raise ValueError('follow stage was not published complete')
    expected = row.get('result')
    if not isinstance(expected, dict) or set(expected) != {'winner', 'scores', 'worlds', 'nodes'}:
        raise ValueError('missing complete follow result')
    rnd, _, admitted, worlds, baseline, _ = restore_exact_stage(row['input'])
    config = row['config']
    if set(config) != {'solver', 'max_hand_cards', 'max_nodes'}:
        raise ValueError('unexpected follow solver config')
    if min_worlds > len(worlds):
        raise ValueError('not enough captured worlds')
    clock = time.perf_counter if clock is None else clock
    totals = [0.0] * len(admitted)
    prefix_totals = None
    elapsed, prefix_count, nodes = 0.0, 0, 0
    costs = []
    prefix_open = True
    for world in worlds:
        start = clock()
        result = rerank_follow(rnd, rnd.turn, admitted, [world],
                               baseline_index=baseline, **config)
        duration = clock() - start
        if not math.isfinite(duration) or duration < 0:
            raise ValueError('invalid measured world duration')
        costs.append(duration)
        elapsed += duration * time_scale
        for index, score in enumerate(result.scores):
            totals[index] += score
        nodes += result.nodes
        if prefix_open and elapsed <= budget_seconds:
            prefix_count += 1
            prefix_totals = list(totals)
        else:
            prefix_open = False

    def choose(means):
        best = max(range(len(means)), key=lambda i: (means[i], -i))
        return best if means[best] > means[baseline] else baseline

    full_means = [value / len(worlds) for value in totals]
    full_winner = choose(full_means)
    full = ExactFollowResult(full_winner, tuple(full_means), len(worlds), nodes)
    if normalized(full) != expected:
        raise ValueError('full follow replay result mismatch')
    served = prefix_count >= min_worlds
    prefix_means = ([value / prefix_count for value in prefix_totals]
                    if served else None)
    selected = choose(prefix_means) if served else baseline

    # This is deliberately after sampled-world replay validation and prefix
    # selection.  The hidden deal is a diagnostic label only; it must never
    # alter either selected action or the simulated serving path.
    truth_scores = None
    full_gain = None
    prefix_gain = None
    if true_deal:
        truth_world = (copy.deepcopy(rnd.hands), copy.deepcopy(rnd.buried))
        truth = rerank_follow(rnd, rnd.turn, admitted, [truth_world],
                              baseline_index=baseline, **config)
        if (truth.worlds != 1 or len(truth.scores) != len(admitted)
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(value) for value in truth.scores)):
            raise ValueError('true-deal replay result mismatch')
        truth_scores = list(truth.scores)
        full_gain = truth_scores[full_winner] - truth_scores[baseline]
        prefix_gain = (truth_scores[selected] - truth_scores[baseline]
                       if served else 0.0)

    claim = ('Simulated stage budget only; double-dummy true-deal scores and '
             'baseline-relative gains are diagnostic, not paired gameplay '
             'strength or deployment evidence.' if true_deal else
             'Simulated stage budget only; no hard-expiry, whole-decision latency, '
             'true-deal or strength claim')
    return dict(schema='exact-follow-prefix-dev-v1', worlds=len(worlds),
                completed_prefix=prefix_count, min_worlds=min_worlds,
                budget_seconds=budget_seconds, time_scale=time_scale,
                world_seconds=costs, served=served, selected=selected,
                full_selected=full_winner, agrees_full=(selected == full_winner),
                prefix_means=prefix_means, full_means=full_means,
                full_world_regret=full_means[full_winner] - full_means[selected],
                true_deal=true_deal, truth_scores=truth_scores,
                full_gain=full_gain, prefix_gain=prefix_gain, claim=claim)


def summarize_follow_prefix_collection(capture, journal, *, budget_seconds,
                                       min_worlds=16, time_scale=1.0,
                                       max_hand_size=8, clock=None,
                                       true_deal=False):
    """Join one completed DEV collection before benchmarking any solver row.

    The denominator is observed follow calls at a fixed maximum hand size, not
    solver eligibility. Abandoned or absent captures stay unmeasured. Only
    served prefixes contribute to served agreement; baseline fallback is separate.
    """
    import math

    if type(true_deal) is not bool:
        raise ValueError('true_deal must be a bool')
    for name, value in [('budget_seconds', budget_seconds), ('time_scale', time_scale)]:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be positive and finite')
    if type(min_worlds) is not int or min_worlds < 1:
        raise ValueError('min_worlds must be a positive integer')
    if type(max_hand_size) is not int or not 1 <= max_hand_size <= 8:
        raise ValueError('max_hand_size must be an integer in [1, 8]')
    schema = 'exact-follow-collection-dev-v1'
    for rows in (capture, journal):
        if len(rows) < 2 or rows[0].get('kind') != 'start' or rows[-1].get('kind') != 'terminal':
            raise ValueError('missing collection start/terminal')
        if any(row.get('kind') in ('start', 'terminal') for row in rows[1:-1]):
            raise ValueError('interior collection boundary')
    header, terminal = capture[0], capture[-1]
    if header.get('schema') != schema or terminal.get('schema') != schema:
        raise ValueError('wrong collection schema')
    if (type(header.get('seed')) is not int
            or not isinstance(header.get('collection'), dict)
            or terminal.get('collection') != header['collection']
            or journal[0].get('identity') != header['collection']
            or journal[0].get('seed') != header.get('seed')
            or journal[0].get('exact_capture') is not True):
        raise ValueError('collection identity mismatch')
    if (terminal.get('failure') is not False or terminal.get('error') is not None
            or terminal.get('reason') not in ('stop_file', 'max_positions', 'max_rounds', 'deadline', 'host_lock')
            or journal[-1].get('reason') != terminal['reason']):
        raise ValueError('collection did not terminate cleanly')
    observations = capture[1:-1]
    if not observations or type(terminal.get('rows')) is not int or terminal['rows'] != len(observations):
        raise ValueError('empty or miscounted capture')
    starts, finished = {}, {}
    for row in journal[1:-1]:
        kind = row.get('kind')
        if kind in ('prepared', 'round_complete'):
            continue
        if kind not in ('decision_start', 'decision', 'decision_error'):
            raise ValueError('unknown journal record')
        index = row.get('decision_index')
        if type(index) is not int or index < 1:
            raise ValueError('invalid decision index')
        if kind == 'decision_start':
            if index != len(starts) + 1 or len(finished) != len(starts):
                raise ValueError('nonsequential decision starts')
            if (type(row.get('lead')) is not bool
                    or type(row.get('max_hand_size')) is not int
                    or type(row.get('hand_size')) is not int
                    or not 0 < row['hand_size'] <= row['max_hand_size']):
                raise ValueError('invalid decision stratum')
            starts[index] = row
        else:
            if index not in starts or index in finished or index != len(starts):
                raise ValueError('unmatched decision completion')
            if kind == 'decision_error':
                raise ValueError('collection contains failed decision')
            if any(row.get(k) != starts[index].get(k) for k in ('round', 'seat', 'lead')):
                raise ValueError('decision completion identity mismatch')
            finished[index] = row
    if set(starts) != set(finished):
        raise ValueError('unfinished decision in journal')
    by_index = {}
    for row in observations:
        index = row.get('decision_index')
        if type(index) is not int or index not in starts or index in by_index:
            raise ValueError('unmatched or duplicate solver observation')
        start = starts[index]
        if (row.get('schema') != 'exact-follow-observation-dev-v1' or start['lead']
                or row.get('collection') != header['collection']
                or row.get('seed') != header['seed']
                or any(row.get(k) != start.get(k) for k in ('game', 'round', 'trick', 'seat'))
                or row.get('played_after_decide') != finished[index].get('played')):
            raise ValueError('solver observation identity mismatch')
        by_index[index] = row
    selected = {i: row for i, row in starts.items()
                if not row['lead'] and row['max_hand_size'] == max_hand_size}
    if not selected:
        raise ValueError('empty requested follow stratum')
    counts = dict(observed=len(selected), no_capture=0, unpublished=0,
                  measured=0, served=0, fallback=0, served_agrees=0, fallback_agrees=0)
    unpublished_by_cause = Counter()
    no_capture_by_cause = Counter()
    results = []
    for index in selected:
        row = by_index.get(index)
        if row is None:
            counts['no_capture'] += 1
            trace = finished[index].get('trace')
            admitted_len = trace.get('admitted__len') if isinstance(trace, dict) else None
            cause = 'admitted__len <= 1' if type(admitted_len) is int and admitted_len <= 1 else 'other'
            no_capture_by_cause[cause] += 1
            continue
        decision = row.get('decision') or {}
        if (decision.get('work_complete') is not True
                or decision.get('exact_follow_attempted') is not True
                or decision.get('exact_follow_abandoned') is not None
                or decision.get('exact_follow_error') is not None):
            counts['unpublished'] += 1
            abandoned = decision.get('exact_follow_abandoned')
            error = decision.get('exact_follow_error')
            if abandoned is not None:
                cause = f'exact_follow_abandoned:{abandoned}'
            elif error is not None:
                cause = f'exact_follow_error:{error}'
            elif decision.get('work_complete') is not True:
                cause = 'work_complete:false'
            else:
                cause = 'exact_follow_attempted:missing'
            unpublished_by_cause[cause] += 1
            continue
        result = evaluate_follow_prefix(row, budget_seconds=budget_seconds,
                                        min_worlds=min_worlds, time_scale=time_scale,
                                        clock=clock, true_deal=true_deal)
        if true_deal:
            truth_scores = result.get('truth_scores')
            if (not isinstance(truth_scores, list) or not truth_scores
                    or any(isinstance(value, bool) or not isinstance(value, (int, float))
                           or not math.isfinite(value) for value in truth_scores)):
                raise ValueError('true-deal result is missing finite truth scores')
            for name in ('full_gain', 'prefix_gain'):
                value = result.get(name)
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value)):
                    raise ValueError(f'true-deal result is missing finite {name}')
            if not result.get('served') and result['prefix_gain'] != 0.0:
                raise ValueError('fallback true-deal prefix gain must be zero')
        counts['measured'] += 1
        group = 'served' if result['served'] else 'fallback'
        counts[group] += 1
        counts[group + '_agrees'] += int(result['agrees_full'])
        results.append(dict(decision_index=index, **result))
    import os
    full_gain_sum = prefix_gain_sum = None
    full_gain_mean = prefix_gain_mean = prefix_gain_ratio = None
    prefix_gain_ratio_reason = None
    if true_deal:
        full_gains = [row['full_gain'] for row in results]
        prefix_gains = [row['prefix_gain'] for row in results]
        full_gain_sum = sum(full_gains)
        prefix_gain_sum = sum(prefix_gains)
        if full_gains:
            full_gain_mean = full_gain_sum / len(full_gains)
            prefix_gain_mean = prefix_gain_sum / len(prefix_gains)
        if full_gain_sum > 0:
            prefix_gain_ratio = prefix_gain_sum / full_gain_sum
        else:
            prefix_gain_ratio_reason = ('no measured rows' if not full_gains else
                                        'full gain sum is not positive')
    claim = ('Simulated stage timing only; double-dummy true-deal scores and '
             'baseline-relative gains are diagnostic, not paired gameplay '
             'strength or deployment evidence.' if true_deal else
             'Simulated stage timing only; no hard-expiry, Fly latency, true-deal '
             'or strength claim.')
    return dict(schema='exact-follow-prefix-summary-dev-v1', counts=counts, rows=results,
                max_hand_size=max_hand_size,
                budget_seconds=budget_seconds, min_worlds=min_worlds, time_scale=time_scale,
                engine='compiled' if os.environ.get('SHENGJI_FAST') == '1' else 'pure',
                capture_on=True,
                no_capture_by_cause=dict(sorted(no_capture_by_cause.items())),
                unpublished_by_cause=dict(sorted(unpublished_by_cause.items())),
                served_fraction_observed=counts['served'] / counts['observed'],
                served_agreement=(counts['served_agrees'] / counts['served'] if counts['served'] else None),
                unmeasured_fraction=(counts['no_capture'] + counts['unpublished']) / counts['observed'],
                true_deal=true_deal, full_gain_sum=full_gain_sum,
                full_gain_mean=full_gain_mean, prefix_gain_sum=prefix_gain_sum,
                prefix_gain_mean=prefix_gain_mean,
                prefix_gain_ratio=prefix_gain_ratio,
                prefix_gain_ratio_reason=prefix_gain_ratio_reason,
                limits=['Observed fixed-size follow calls, not solver eligibility or population prevalence.',
                        'Completion-conditioned full-world replay; missing/abandoned solves remain unmeasured.',
                        'Capture runs inside the served stage budget; capture-caused abandonment is not separable (no per-row capture_seconds).',
                        'The collection header does not record its engine; this summary records the reader engine.',
                        claim])


def fingerprint(rnd):
    state = dict(vars(rnd))
    # Ordering memoization is execution history, not game state.
    state['ordering'] = {k: v for k, v in vars(rnd.ordering).items()
                         if not k.startswith('_')}
    return normalized(state)


def restore(packet):
    if packet['schema'] != 'lead-root-capture-dev-v1':
        raise ValueError('unknown schema')
    rnd = round_from_setup(packet['deck'], packet['setup'])
    rnd.first_round = packet['first_round']
    for event in packet['plays']:
        before = Counter(rnd.hands[event['seat']])
        rnd.play(event['seat'], event['attempted'])
        if before - Counter(rnd.hands[event['seat']]) != Counter(event['accepted']):
            raise ValueError('accepted cards drift')
    if fingerprint(rnd) != packet['root']:
        raise ValueError('root state drift')
    return rnd


def restore_with_ledger(packet):
    rnd = restore(packet)
    saved = packet['ledger']
    ledger = RefusalLedger()
    ledger.key = tuple(saved['key']) if saved['key'] is not None else None
    if ledger.key is not None and ledger.key != tuple(rnd.deck):
        raise ValueError('ledger belongs to another round')
    ledger.refusals = [Refusal(seat=r['seat'], attempted=tuple(r['attempted']),
                              forced=tuple(r['forced']), trick_index=r['trick_index'])
                       for r in saved['refusals']]
    if ledger.refusals and ledger.key is None:
        raise ValueError('nonempty unbound ledger')
    if not all(on_record(rnd, r) for r in ledger.refusals):
        raise ValueError('ledger unsupported by replay')
    return rnd, ledger


def _stage_worlds(rnd, worlds, seat):
    """Validate and copy the sampled exact-stage inputs at a captured root."""
    if type(seat) is not int or not 0 <= seat < 4 or rnd.turn != seat:
        raise ValueError('exact stage acting seat drift')
    if not isinstance(worlds, (list, tuple)) or not worlds:
        raise ValueError('exact stage requires sampled worlds')
    expected = Counter(card for hand in rnd.hands for card in hand)
    expected += Counter(rnd.buried)
    shape = [len(hand) for hand in rnd.hands]
    copied = []
    for world in worlds:
        if not isinstance(world, (list, tuple)) or len(world) != 2:
            raise ValueError('malformed sampled world')
        hands, buried = world
        if (not isinstance(hands, (list, tuple)) or len(hands) != 4
                or not isinstance(buried, (list, tuple))):
            raise ValueError('malformed sampled world')
        if [len(hand) for hand in hands] != shape:
            raise ValueError('sampled world changes public hand sizes')
        if Counter(card for hand in hands for card in hand) + Counter(buried) != expected:
            raise ValueError('sampled world changes card multiset')
        if Counter(hands[seat]) != Counter(rnd.hands[seat]):
            raise ValueError('sampled world changes the acting hand')
        copied.append([copy.deepcopy([list(hand) for hand in hands]), list(buried)])
    return copied


def restore_exact_stage(packet):
    """Restore a DEV exact-stage packet without model or RNG reconstruction.

    The returned stage inputs are copies.  ``worlds`` are sampled hidden-world
    inputs, not a claim about the true deal; the replay is the only engine root.
    """
    if packet.get('schema') != 'exact-stage-capture-dev-v1':
        raise ValueError('unknown exact-stage schema')
    replay = packet.get('replay')
    if not isinstance(replay, dict):
        raise ValueError('exact stage replay is missing')
    rnd, ledger = restore_with_ledger(replay)
    if rnd.phase != 'play' or rnd.trick is None:
        raise ValueError('exact stage requires a play root')
    seat = packet.get('seat')
    if type(seat) is not int or rnd.turn != seat:
        raise ValueError('exact stage acting seat drift')
    admitted = packet.get('admitted')
    if not isinstance(admitted, list) or not admitted:
        raise ValueError('malformed admitted actions')
    action_keys = []
    hand_counts = Counter(rnd.hands[seat])
    for action in admitted:
        key = _action_multiset(action)
        if Counter(action) - hand_counts:
            raise ValueError('action cards outside acting hand')
        if key in action_keys:
            raise ValueError('duplicate admitted action')
        action_keys.append(key)
    baseline = packet.get('baseline_index')
    if type(baseline) is not int or not 0 <= baseline < len(admitted):
        raise ValueError('baseline index is outside the ballot')
    actual = packet.get('actual_action')
    if actual is not None:
        actual_key = _action_multiset(actual)
        if actual_key not in action_keys:
            raise ValueError('actual action is outside the ballot')
    worlds = _stage_worlds(rnd, packet.get('worlds'), seat)
    return rnd, ledger, copy.deepcopy(admitted), worlds, baseline, copy.deepcopy(actual)


class LeadCapture:
    def __init__(self, rnd):
        if rnd.phase != 'play' or rnd.history or rnd.trick.plays:
            raise ValueError('capture must start immediately after bury')
        setup = setup_from_round(rnd)
        setup['buried'] = list(rnd.buried)
        setup['declarations'] = ([{'seat': rnd.declaration['seat'],
                                  'cards': list(rnd.declaration['cards'])}]
                                 if rnd.declaration else [])
        setup['passed'] = sorted(rnd.passed)
        self.packet = dict(schema='lead-root-capture-dev-v1', deck=list(rnd.deck),
                           setup=setup, first_round=rnd.first_round, plays=[],
                           root=fingerprint(rnd))
        # Refuse unsupported setup compression rather than save unreplayable roots.
        restore(self.packet)

    def committed(self, rnd, seat, attempted):
        trick = rnd.trick if rnd.trick and rnd.trick.plays else rnd.last_trick
        play = trick.plays[-1]
        if play.seat != seat:
            raise ValueError('committed seat mismatch')
        self.packet['plays'].append(dict(seat=seat, attempted=list(attempted),
                                         accepted=list(play.cards)))

    def capture(self, rnd, *, ledger, decision):
        if rnd.phase != 'play' or rnd.trick.plays:
            raise ValueError('not a lead root')
        if ledger.key is not None and tuple(rnd.deck) != ledger.key:
            raise ValueError('ledger belongs to another round')
        packet = copy.deepcopy(self.packet)
        packet['root'] = fingerprint(rnd)
        packet['ledger'] = normalized(vars(ledger))
        packet['decision'] = normalized(decision)
        packet['limits'] = ['Full hidden deal: DEV-only, not policy input.',
                            'Exact engine state and observed ledger only; no bot RNG restoration.',
                            'No claim of historical provenance or playing strength.']
        restore_with_ledger(packet)
        return packet

    def capture_exact_stage(self, rnd, *, ledger, admitted, worlds,
                            baseline_index=0, actual_action=None):
        """Capture a play root and its immutable exact-stage inputs.

        This is opt-in collector plumbing.  The caller commits every observed
        play as usual, then passes the exact ballot/worlds sent to
        the exact stage; no model, RNG, or serving path is reconstructed.
        """
        if rnd.phase != 'play' or rnd.trick is None:
            raise ValueError('exact stage requires a play root')
        replay = copy.deepcopy(self.packet)
        replay['root'] = fingerprint(rnd)
        replay['ledger'] = normalized(vars(ledger))
        replay['limits'] = [
            'Full hidden deal: DEV-only, not policy input.',
            'Exact engine state and observed ledger only; no bot RNG restoration.',
            'No claim of historical provenance or playing strength.',
        ]
        replay['schema'] = 'lead-root-capture-dev-v1'
        restore_with_ledger(replay)
        admitted_copy = normalized(admitted)
        if (not isinstance(admitted_copy, list) or not admitted_copy
                or any(not isinstance(action, list) or not action
                       for action in admitted_copy)):
            raise ValueError('malformed admitted actions')
        if type(baseline_index) is not int or not 0 <= baseline_index < len(admitted_copy):
            raise ValueError('baseline index is outside the ballot')
        if actual_action is not None:
            actual_key = _action_multiset(normalized(actual_action))
            admitted_keys = [_action_multiset(action) for action in admitted_copy]
            if actual_key not in admitted_keys:
                raise ValueError('actual action is outside the ballot')
        packet = dict(schema='exact-stage-capture-dev-v1', replay=replay,
                      seat=rnd.turn, admitted=admitted_copy,
                      worlds=normalized(worlds), baseline_index=baseline_index,
                      actual_action=normalized(actual_action),
                      limits=['Sampled worlds are exact-stage inputs, not true-deal labels.',
                              'No model or RNG reconstruction; no serving changes.'])
        restore_exact_stage(packet)
        return packet
