"""Construct an unarmed command plan for the existing screen queue; never dispatch."""
from pathlib import Path

from screen_probe import admit_pair


FIRST_WINDOWS = frozenset((0, 3, 5, 8))
RANKS = '2,3,4,5,6,7,8,9,10,J,Q,K,A'
CLUSTERS = 520


def queue_windows(arms, seeds, output, *, workers=14):
    """Pure command construction; no seed clearance or launch authority implied."""
    if (len(seeds) != 10 or any(type(seed) is not int or seed < 0 for seed in seeds)
            or any(b < a + CLUSTERS for a, b in zip(sorted(seeds), sorted(seeds)[1:]))):
        raise ValueError('ten distinct nonoverlapping integer seed windows required')
    if type(workers) is not int or not 1 <= workers <= 14:
        raise ValueError('workers must be in 1..14; host qualification still required')
    if not Path(output).is_absolute():
        raise ValueError('absolute output root required')
    if len(arms) != 2 or arms[0]['name'] == arms[1]['name']:
        raise ValueError('distinct candidate and comparator required')
    windows = []
    for side, arm in zip(('candidate', 'comparator'), arms, strict=True):
        prefix = 's58combo-' + side
        for index, seed in enumerate(seeds):
            kind = 'first' if index in FIRST_WINDOWS else 'fixed_banker'
            ranks = '2' if kind == 'first' else RANKS
            argv = ['--arm-policy', arm['name'], '--out', str(output), '--name', prefix,
                    '--workers', str(workers), '--clusters', str(CLUSTERS),
                    '--seeds', str(seed), '--decision-deadline', '300',
                    '--trump-ranks', ranks, '--round-kind', kind]
            windows.append(dict(side=side, seed=seed, round_kind=kind, ranks=ranks,
                                output=str(Path(output) / f'{prefix}-{seed}'), argv=argv))
    return windows


def build_plan(envs, seeds, output, *, profile='half-budget-lgfd1000', workers=14):
    """Bind actual packages/worker identities before producing queue arguments."""
    # Reject malformed schedules before package loading or child construction.
    queue_windows([{'name': 'candidate'}, {'name': 'comparator'}], seeds, output, workers=workers)
    arms = admit_pair(envs, profile=profile)
    return dict(schema='s58combo-unarmed-window-plan-v1', profile=profile,
                module='shengji.train.cwv_screen_queue',
                arms={side: dict(**arm, environment=dict(env))
                      for side, arm, env in zip(('candidate', 'comparator'), arms, envs, strict=True)},
                windows=queue_windows(arms, seeds, output, workers=workers),
                dispatch_authorized=False,
                pending=['seed/exposure clearance', 'host qualification',
                         'sealed reader and terminal contract', 'independent review', 'RELEASE'])
