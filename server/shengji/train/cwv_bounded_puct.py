"""DEV determinized PUCT kernel; no registry or production defaults.

Each supplied sampled world owns a tree. Every sweep gives each world one
simulation, then batches all learned leaves. Root choice aggregates visits,
NOT the best world's value. Opponent nodes minimize root-team signed levels.
This is determinized lookahead (strategy fusion remains), not information-set
MCTS: descendants can react to the sampled hidden hands. Callers must use the
production constrained sampler, never live opponent hands, to construct roots.
"""
from dataclasses import dataclass, field
import math
import time

import numpy as np

from ..ai.cwv_puct import leaf_copy
from ..harvest.legal import enumerate_legal
from .cwv_truncated_value import continuation_values


@dataclass(frozen=True)
class PuctConfig:
    sweeps: int = 8
    depth: int = 8
    batch_size: int = 32
    exploration: float = 1.5
    widening: float = 2.0
    widening_power: float = 0.5

    def __post_init__(self):
        for name in ('sweeps', 'depth', 'batch_size'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f'{name} must be a positive integer')
        if not (math.isfinite(self.exploration) and self.exploration >= 0
                and math.isfinite(self.widening) and self.widening >= 1
                and 0 < self.widening_power <= 1):
            raise ValueError('invalid PUCT or widening coefficient')


@dataclass
class Node:
    state: object
    visits: int = 0
    total: float = 0.
    actions: list = field(default_factory=list)
    priors: np.ndarray | None = None
    children: dict = field(default_factory=dict)


def _root_legal_key(state):
    """Only enumerator inputs; hidden hands affect priors/transitions, not legality."""
    lead = (tuple(sorted(state.trick.plays[0].cards))
            if state.trick.plays else None)
    return (state.phase, state.turn, state.ordering.trump_suit,
            state.ordering.trump_rank, tuple(sorted(state.hands[state.turn])), lead)


def search_worlds(worlds, seat, *, prior_logits, evaluator, config=PuctConfig(), profile=False,
                  reuse_root_actions=False):
    """Prior callback receives ONLY a private determinized state and legal set.

    Scores are logits in enumerator order for the ACTING seat. Exhaustive
    enumeration is retained; widening limits child evaluation, not enumeration.
    One in-flight path per world eliminates virtual-loss/batch-order effects.
    A hard move deadline belongs to the existing supervising screen process.
    """
    if not worlds or type(seat) is not int or not 0 <= seat < 4:
        raise ValueError('nonempty sampled worlds and valid root seat required')
    for world in worlds:
        if (world.phase != 'play' or world.turn != seat
                or not getattr(world, '_determinized_world', False)):
            raise ValueError('roots must be determinized play states at root turn')
    started = time.perf_counter() if profile else 0.
    timings = dict(enumeration_seconds=0., prior_seconds=0., transition_seconds=0.,
                   leaf_seconds=0.)
    roots = [Node(leaf_copy(world)) for world in worlds]
    root_ids = {id(root) for root in roots}
    root_actions = {}
    reuse = dict(hits=0, misses=0)
    counts = dict(model_rows=0, model_batches=0, terminal_rows=0,
                  prior_rows=0, legal_actions=0, expanded_nodes=0)
    depth_histogram = {}

    def expand(node):
        if node.priors is not None:
            return
        tick = time.perf_counter() if profile else 0.
        key = (_root_legal_key(node.state)
               if reuse_root_actions and id(node) in root_ids else None)
        actions = root_actions.get(key) if key is not None else None
        if actions is None:
            legal = enumerate_legal(node.state, node.state.turn, cap=None)
            if not legal.complete or not legal.actions:
                raise ValueError('PUCT requires the exhaustive legal set')
            actions = tuple(tuple(a) for a in legal.actions)
            if key is not None:
                root_actions[key] = actions
                reuse['misses'] += 1
        elif key is not None:
            reuse['hits'] += 1
        if profile:
            timings['enumeration_seconds'] += time.perf_counter() - tick
        tick = time.perf_counter() if profile else 0.
        logits = np.asarray(prior_logits(node.state, node.state.turn, list(actions)), dtype=float)
        if profile:
            timings['prior_seconds'] += time.perf_counter() - tick
        if logits.shape != (len(actions),) or not np.isfinite(logits).all():
            raise ValueError('one finite policy logit required per legal action')
        order = np.argsort(-logits, kind='stable')
        weights = np.exp(logits - logits.max())
        node.actions = [actions[i] for i in order]
        node.priors = (weights / weights.sum())[order]
        counts['prior_rows'] += 1
        counts['legal_actions'] += len(actions)
        counts['expanded_nodes'] += 1

    for _ in range(config.sweeps):
        paths, leaves = [], []
        for root in roots:
            node, path = root, [root]
            for _depth in range(config.depth):
                if node.state.phase == 'round_end':
                    break
                expand(node)
                width = min(len(node.actions), max(1, math.ceil(
                    config.widening * (node.visits + 1) ** config.widening_power)))
                sign = 1 if node.state.turn % 2 == seat % 2 else -1
                fpu = node.total / node.visits if node.visits else 0.

                def score(i):
                    child = node.children.get(node.actions[i])
                    n = child.visits if child is not None else 0
                    q = child.total / n if n else fpu
                    return sign * q + config.exploration * node.priors[i] * math.sqrt(node.visits + 1) / (1 + n)

                action = node.actions[max(range(width), key=score)]
                fresh = action not in node.children
                if fresh:
                    tick = time.perf_counter() if profile else 0.
                    child_state = leaf_copy(node.state)
                    child_state.play(child_state.turn, list(action))
                    node.children[action] = Node(child_state)
                    if profile:
                        timings['transition_seconds'] += time.perf_counter() - tick
                # Children are per attempted action in ONE fixed world: failed
                # throws cannot alias states from other worlds or attempts.
                node = node.children[action]
                path.append(node)
                if fresh:
                    break
            paths.append(path)
            leaves.append(node.state)
            depth = len(path) - 1
            depth_histogram[depth] = depth_histogram.get(depth, 0) + 1
        tick = time.perf_counter() if profile else 0.
        out = continuation_values(leaves, [seat] * len(leaves),
                                  [len(s.history) for s in leaves], evaluator=evaluator,
                                  tricks=0, batch_size=config.batch_size)
        if profile:
            timings['leaf_seconds'] += time.perf_counter() - tick
        for name in ('model_rows', 'model_batches', 'terminal_rows'):
            counts[name] += getattr(out, name)
        for path, value in zip(paths, out.values, strict=True):
            for node in path:
                node.visits += 1
                node.total += float(value)
    visits, totals = {}, {}
    for root in roots:
        for action, child in root.children.items():
            visits[action] = visits.get(action, 0) + child.visits
            totals[action] = totals.get(action, 0.) + child.total
    # Visit aggregation gives every world the same vote budget. Q tie-breaks
    # are conditional on visits, not an unbiased common-world action estimate.
    chosen = max(sorted(visits), key=lambda a: (visits[a], totals[a] / visits[a]))
    result = dict(action=list(chosen), visits=visits, totals=totals,
                world_visits=[r.visits for r in roots], simulations=len(roots) * config.sweeps,
                diagnostics=dict(depth_histogram=depth_histogram,
                    root_legal_counts=[len(r.actions) for r in roots],
                    root_visited_actions=[len(r.children) for r in roots],
                    root_visited_prior_mass=[float(sum(
                        r.priors[i] for i, action in enumerate(r.actions)
                        if action in r.children)) for r in roots]),
                counts=counts, units='root-team-final-signed-levels',
                limitation='determinization-and-strategy-fusion')
    if reuse_root_actions:
        result['root_enumeration_reuse'] = reuse
    if profile:
        timings['search_seconds'] = time.perf_counter() - started
        timings['other_seconds'] = max(0., timings['search_seconds'] - sum(
            timings[k] for k in ('enumeration_seconds', 'prior_seconds',
                                'transition_seconds', 'leaf_seconds')))
        result['timings'] = timings
    return result


from .cwv_prior_admission import CWVPriorAdmissionBot, root_clone
from ..ai.cwv_policy import sample_worlds, CWVError


class CWVBoundedPuctBot(CWVPriorAdmissionBot):
    """Research adapter sharing the verified prior loader and legal sampler.

    Shortlist configuration supplies world count ONLY; shortlist admission,
    selection and report are not called. Prior threshold/top do not prune this
    tree: every expanded node ranks its exhaustive set. Declare/bury inherited.
    """

    def __init__(self, *args, puct_config=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.puct_config = puct_config or PuctConfig()
        self.puct_totals = dict.fromkeys(('decisions', 'simulations', 'model_rows',
                                        'model_batches', 'terminal_rows', 'prior_rows',
                                        'legal_actions', 'expanded_nodes'), 0)

    def _tree_prior(self, world, seat, actions):
        if not getattr(world, '_determinized_world', False):
            raise ValueError('policy head requires a sampled world')
        return self._prior_scores(world, seat, actions, [(world.hands, world.buried)])[0]

    def decide_play(self, rnd, seat):
        import time
        from dataclasses import asdict
        started = time.perf_counter()
        self.last_decision_record = None
        worlds, attempts = sample_worlds(self, rnd, seat, self.shortlist_config.worlds)
        if len(worlds) != self.shortlist_config.worlds:
            raise CWVError('bounded PUCT sampled-world pool underfilled')
        roots = [root_clone(rnd, hands, buried) for hands, buried in worlds]
        result = search_worlds(roots, seat, prior_logits=self._tree_prior,
                               evaluator=self.evaluator, config=self.puct_config)
        counts = result['counts']
        self.puct_totals['decisions'] += 1
        self.puct_totals['simulations'] += result['simulations']
        for key, value in counts.items():
            self.puct_totals[key] += value
        self.last_decision_record = {
            'schema': 'bounded-puct-decision-v1', 'seat': seat,
            'elapsed_seconds': time.perf_counter() - started,
            'bounded_puct': {
                'config': asdict(self.puct_config), 'worlds': len(worlds),
                'attempts': attempts, 'world_visits': result['world_visits'],
                'simulations': result['simulations'], **counts,
                'units': result['units'], 'limitation': result['limitation'],
                'prior_checkpoint_sha256': self.prior_config.checkpoint_sha256,
                'root_actions': [dict(cards=list(a), visits=n,
                                      value_sum=result['totals'][a])
                                 for a, n in sorted(result['visits'].items())],
            },
        }
        return result['action']
