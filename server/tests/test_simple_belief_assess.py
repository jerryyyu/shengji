import numpy as np
import pytest

from shengji.train.simple_belief_assess import _assess_deal
from shengji.train.simple_belief_data import encode_record, select_records, record_deal_key
from test_simple_belief_data import record


def test_real_reference_wiring_preserves_nonzero_metric_and_reuses(tmp_path, monkeypatch):
    r = record()
    x, mask, truth = encode_record(r)
    # Oracle prediction is test-only; actual readout gets model predictions.
    task = (record_deal_key(r), select_records([r], 1), np.eye(3)[truth][None],
            mask[None], truth[None], str(tmp_path / 'deal.json'), 'identity', 16)
    result = _assess_deal(task)
    row = result['rows'][0]
    assert row['model_brier'] == 0
    assert row['reference_raw_brier'] > row['reference_corrected_brier'] > 0
    assert row['uncertain_cells'] > 0 and row['reference_unique_worlds'] > 1
    def forbidden(*args, **kwargs):
        raise AssertionError('completed reference must not rerun')
    monkeypatch.setattr('shengji.train.simple_belief_assess.corrected_reference', forbidden)
    assert _assess_deal(task) == result
    with pytest.raises(ValueError, match='different recipe'):
        _assess_deal((*task[:-2], 'changed', task[-1]))
