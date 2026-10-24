"""Project only the decision prefix needed by the same-root replay consumer."""
from copy import deepcopy

from locator import bind_locator


LOCATOR = dict(seed=218060912, kind='fixed_banker', rank='4', index=105,
               phase='P', seat=2, trick=0, lead=True, hand=25,
               release46_action=['D4', 'D4'], exploiter_action=['H10'])
FIELDS = ('seed', 'round_kind', 'trump_rank', 'planned_banker', 'banker',
          'trump', 'mirror')


def project_pair(rows, locator=LOCATOR):
    """Validate the exact root and omit all play after its first divergence."""
    if not isinstance(rows, list) or len(rows) != 2:
        raise ValueError('exactly two mirror records required')
    projected = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('invalid mirror record')
        if (type(row.get('seed')) is not int or row['seed'] != locator['seed']
                or row.get('round_kind') != locator['kind']
                or row.get('trump_rank') != locator['rank']
                or type(row.get('mirror')) is not int):
            raise ValueError('record outside named extraction')
        trace, history = row.get('dtrace'), row.get('history')
        if not isinstance(trace, list) or ('history' in row and not isinstance(history, list)):
            raise ValueError('missing replay evidence')
        index = locator['index']
        prefix = trace[:index + 1]
        if len(prefix) != index + 1:
            raise ValueError('incomplete decision prefix')
        if any(not isinstance(entry, list) or len(entry) != 6 for entry in prefix):
            raise ValueError('invalid decision prefix')
        plays = sum(entry[0] == 'P' for entry in prefix)
        if history is not None and len(history) < plays:
            raise ValueError('incomplete accepted-play prefix')
        item = {key: deepcopy(row[key]) for key in FIELDS}
        item['dtrace'] = deepcopy(prefix)
        if history is not None:
            item['history'] = deepcopy(history[:plays])
        if 'buried' in row:
            item['buried'] = deepcopy(row['buried'])
        projected.append(item)
    _, witness = bind_locator(locator, projected)
    return dict(schema='s61-same-root-prefix-v1', locator=deepcopy(locator),
                rows=sorted(projected, key=lambda row: row['mirror']), witness=witness)
