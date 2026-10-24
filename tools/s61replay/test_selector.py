import hashlib
import io
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from selector import select_pair
from test_locator import fixture


def source():
    locator, rows, _ = fixture()
    encoded = [json.dumps(dict(arm='combo', seed=row['seed'], mirror=row['mirror'],
                               **{k:v for k,v in row.items() if k not in ('seed','mirror')})).encode()+b'\n'
               for row in rows]
    # An irrelevant body cannot be decoded, proving only its identity is read.
    other = b'{"arm": "combo", "seed": 888, "mirror": 0, FORBIDDEN_OUTCOME\n'
    return locator, encoded[1]+other+encoded[0]


def test_sealed_unordered_selection_reaches_replay_consumer():
    locator, raw = source()
    result = select_pair(io.BytesIO(raw), hashlib.sha256(raw).hexdigest(),
                         locator=locator, expected_rows=3)
    assert [r['mirror'] for r in result['rows']] == [0, 1]
    assert result['witness']['play_index'] == 0
    assert 'FORBIDDEN_OUTCOME' not in str(result)


@pytest.mark.parametrize('defect', ['seal', 'duplicate', 'missing', 'header', 'count'])
def test_selector_refuses_invalid_source(defect):
    locator, raw = source()
    if defect == 'duplicate': raw = raw.replace(b'"mirror": 1', b'"mirror": 0', 1)
    elif defect == 'missing': raw = raw.replace(b'"seed": 19', b'"seed": 20', 1)
    elif defect == 'header': raw = b'BAD'+raw
    digest = '0'*64 if defect == 'seal' else hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):
        select_pair(io.BytesIO(raw), digest, locator=locator,
                    expected_rows=4 if defect == 'count' else 3)
