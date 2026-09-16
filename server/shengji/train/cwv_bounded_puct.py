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


def search_worlds(worlds, seat, *, prior_logits, evaluator, config=PuctConfig(), profile=False,
                  root_warmup_actions=(), root_warmup_top=0):
    """Prior callback receives ONLY a private determinized state and legal set.

    Scores are logits in enumerator order for the ACTING seat. Exhaustive
    enumeration is retained; widening limits child evaluation, not enumeration.
    One in-flight path per world eliminates virtual-loss/batch-order effects.
    A hard move deadline belongs to the existing supervising screen process.
    Optional common root actions each receive one evaluation in EVERY world
    before adaptive sweeps. These are additional simulations, explicitly counted;
    the returned warmup matrix is comparable evidence, unlike adaptive Q values.
    root_warmup_top adds proposals ranked by mean normalized policy probability
    across all roots, retaining every caller-supplied anchor.
    """
    if not worlds or type(seat) is not int or not 0 <= seat < 4:
        raise ValueError('nonempty sampled worlds and valid root seat required')
    if type(root_warmup_top) is not int or root_warmup_top < 0:
        raise ValueError('root_warmup_top must be a nonnegative integer')
    for world in worlds:
        if (world.phase != 'play' or world.turn != seat
                or not getattr(world, '_determinized_world', False)):
            raise ValueError('roots must be determinized play states at root turn')
    warmup_actions = tuple(tuple(sorted(a)) for a in root_warmup_actions)
    if len(set(warmup_actions)) != len(warmup_actions):
        raise ValueError('common root actions must be distinct')
    if warmup_actions:
        from ..harvest.legal import is_legal
        if any(not is_legal(world, seat, action)
               for world in worlds for action in warmup_actions):
            raise ValueError('common root actions must be legal in every world')
    started = time.perf_counter() if profile else 0.
    timings = dict(enumeration_seconds=0., prior_seconds=0., transition_seconds=0.,
                   leaf_seconds=0.)
    roots = [Node(leaf_copy(world)) for world in worlds]
    counts = dict(model_rows=0, model_batches=0, terminal_rows=0,
                  prior_rows=0, legal_actions=0, expanded_nodes=0)
    depth_histogram = {}

    def expand(node):
        if node.priors is not None:
            return
        tick = time.perf_counter() if profile else 0.
        legal = enumerate_legal(node.state, node.state.turn, cap=None)
        if profile:
            timings['enumeration_seconds'] += time.perf_counter() - tick
        if not legal.complete or not legal.actions:
            raise ValueError('PUCT requires the exhaustive legal set')
        actions = [tuple(a) for a in legal.actions]
        tick = time.perf_counter() if profile else 0.
        logits = np.asarray(prior_logits(node.state, node.state.turn, actions), dtype=float)
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

    warmup_anchors = warmup_actions
    if root_warmup_top:
        for root in roots:
            expand(root)
        keys = set(roots[0].actions)
        if any(set(root.actions) != keys for root in roots):
            raise ValueError('common policy proposals require identical root legal populations')
        masses = dict.fromkeys(keys, 0.)
        for root in roots:
            for action, probability in zip(root.actions, root.priors, strict=True):
                masses[action] += float(probability) / len(roots)
        additions = sorted(keys - set(warmup_actions), key=lambda a: (-masses[a], a))[
            :root_warmup_top]
        warmup_actions = (*warmup_actions, *additions)
    warmup_values = []
    for action in warmup_actions:
        children = []
        for root in roots:
            expand(root)
            tick = time.perf_counter() if profile else 0.
            state = leaf_copy(root.state)
            state.play(state.turn, list(action))
            child = Node(state)
            root.children[action] = child
            children.append(child)
            if profile:
                timings['transition_seconds'] += time.perf_counter() - tick
        tick = time.perf_counter() if profile else 0.
        values = continuation_values([child.state for child in children],
            [seat] * len(children), [len(root.state.history) for root in roots],
            evaluator=evaluator, tricks=0, batch_size=config.batch_size)
        if profile:
            timings['leaf_seconds'] += time.perf_counter() - tick
        for name in ('model_rows', 'model_batches', 'terminal_rows'):
            counts[name] += getattr(values, name)
        warmup_values.append(values.values.tolist())
        for root, child, value in zip(roots, children, values.values, strict=True):
            child.visits = 1
            child.total = float(value)
            root.visits += 1
            root.total += float(value)
        depth_histogram[1] = depth_histogram.get(1, 0) + len(roots)

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
                world_visits=[r.visits for r in roots],
                simulations=len(roots) * (config.sweeps + len(warmup_actions)),
                diagnostics=dict(depth_histogram=depth_histogram,
                    root_legal_counts=[len(r.actions) for r in roots],
                    root_visited_actions=[len(r.children) for r in roots],
                    root_visited_prior_mass=[float(sum(
                        r.priors[i] for i, action in enumerate(r.actions)
                        if action in r.children)) for r in roots]),
                counts=counts, units='root-team-final-signed-levels',
                limitation='determinization-and-strategy-fusion')
    if warmup_actions:
        result['common_root_warmup'] = dict(
            actions=[list(a) for a in warmup_actions],
            anchors=[list(a) for a in warmup_anchors],
            policy_additions_requested=root_warmup_top,
            policy_additions_actual=len(warmup_actions) - len(warmup_anchors),
            values_by_action_world=warmup_values,
            means=np.mean(warmup_values, axis=1).tolist(),
            simulations=len(roots) * len(warmup_actions),
            adaptive_simulations=len(roots) * config.sweeps,
            limitation='immediate-value-leaves; adaptive final Q remains visit-conditional')
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
    Opt-in root warmup retains the MC generator's candidates plus common policy
    proposals; it does not promise to retain the release27 W32-selected winner.
    """

    def __init__(self, *args, puct_config=None, root_warmup_top=0, **kwargs):
        if type(root_warmup_top) is not int or root_warmup_top < 0:
            raise ValueError('root_warmup_top must be a nonnegative integer')
        super().__init__(*args, **kwargs)
        self.root_warmup_top = root_warmup_top
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
        anchors = ()
        if self.root_warmup_top:
            from ..ai.mcbot import MCBot
            # Preserve the literal MC candidate generator, not a second sampled
            # W32 ranking pass. All inputs here are public/own-hand information.
            anchors = tuple(dict.fromkeys(tuple(sorted(a))
                            for a in MCBot._candidates(self, rnd, seat)))
        result = search_worlds(roots, seat, prior_logits=self._tree_prior,
                               evaluator=self.evaluator, config=self.puct_config,
                               root_warmup_actions=anchors,
                               root_warmup_top=self.root_warmup_top)
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
        if 'common_root_warmup' in result:
            self.last_decision_record['bounded_puct']['common_root_warmup'] = result['common_root_warmup']
        return result['action']
