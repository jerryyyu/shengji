import io
import json
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.rl.encode import CARD_INDEX
from shengji.train.r4_inference_service import serve
from shengji.train.simple_belief_r4 import ownership_array


def test_sparse_r4_mapping_does_not_fabricate_missing_cells():
    actor = SimpleNamespace(hidden_burial_size=0, actor_known_burial=(('C2', 2),),
                            deductions=SimpleNamespace(unseen=(('BJ', 1),)))
    cells = [{'card': 'BJ', 'receiver': f'seat-relative-{i}',
              'count_probability_ppb': [i*100_000_000, 1_000_000_000-i*100_000_000, 0]}
             for i in range(1, 4)]
    payload = {'probability_scale': 1_000_000_000, 'count_probabilities': cells}
    p = ownership_array(actor, payload)
    assert p.shape == (4, 54, 3)
    assert p[0, CARD_INDEX['BJ'], 1] == .9
    assert p[2, CARD_INDEX['BJ'], 1] == .7
    np.testing.assert_array_equal(p[3, CARD_INDEX['C2']], [0, 0, 1])
    np.testing.assert_array_equal(p[0, CARD_INDEX['D3']], [1, 0, 0])
    with pytest.raises(ValueError, match='cells missing'):
        ownership_array(actor, {**payload, 'count_probabilities': cells[:-1]})
    with pytest.raises(ValueError, match='population differs'):
        ownership_array(actor, {**payload, 'count_probabilities': cells + cells[:1]})


def test_actor_only_service_rejects_hidden_envelope_before_predicting():
    def never(_):
        pytest.fail('hidden state reached predictor')
    request = {'request_id': 1, 'actor': {}, 'worlds': ['hidden']}
    with pytest.raises(ValueError, match='actor-only inference request'):
        serve(never, {}, io.StringIO(json.dumps(request)+'\n'), io.StringIO())
