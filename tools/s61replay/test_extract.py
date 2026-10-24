import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import project_pair
from locator import bind_locator
from test_locator import fixture


def test_projection_feeds_real_replay_without_future_outcomes():
    locator, rows, original = fixture()
    for row in rows:
        row['signed_levels'] = 999
        row['history'].append(['FORBIDDEN_FUTURE'])
        row['dtrace'].append(['FORBIDDEN_FUTURE'])
    result = project_pair(rows, locator)
    root, witness = bind_locator(result['locator'], result['rows'])
    assert root.hands == original.hands
    assert witness == result['witness']
    assert len(result['rows'][0]['dtrace']) == 106
    assert len(result['rows'][0]['history']) == 1
    assert 'signed_levels' not in result['rows'][0]
    assert 'FORBIDDEN_FUTURE' not in str(result)
    assert len(rows[0]['history']) > 1


@pytest.mark.parametrize('defect', ['seed', 'mirror', 'prefix', 'accepted', 'missing'])
def test_projection_refuses_identity_and_consumer_drift(defect):
    locator, rows, _ = fixture()
    if defect == 'seed': rows[0]['seed'] += 1
    elif defect == 'mirror': rows[0]['mirror'] = True
    elif defect == 'prefix': rows[0]['dtrace'] = []
    elif defect == 'accepted': rows[0]['history'][0][1] = ['SJ']
    else: rows.pop()
    with pytest.raises(ValueError):
        project_pair(rows, locator)
