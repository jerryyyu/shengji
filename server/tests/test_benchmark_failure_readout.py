import json

import pytest

from scripts import production_llm_panel_readout as readout
from shengji.luna.benchmark_failure_protocol import PRESERVE_ILLEGAL
from test_production_llm_panel_readout import _panel


def amended(tmp_path, *, failure=True):
    panel = _panel(tmp_path)
    path = panel['m1-prior'] / 'result.json'
    report = json.loads(path.read_text())
    report['config'].update(failure_protocol=PRESERVE_ILLEGAL, illegal_failure_limit=8)
    row = report['mirrors'][1]
    if failure:
        row.update(complete=False, error='IllegalPlay: follow suit',
                   events=[{'seat': 3, 'attempted_cards': ['C7']}],
                   failure={'schema': 'benchmark-action-failure-v1',
                            'category': 'model_illegal_action', 'stage': 'engine_play',
                            'seat': 3, 'event_index': 0, 'attempted_cards': ['C7']})
        row.pop('signed_levels')
    path.write_text(json.dumps(report))
    return panel, path, report


def test_actual_panel_reader_exposes_both_endpoints_with_correct_sign(tmp_path):
    panel, _, _ = amended(tmp_path)
    row = readout.analyze_panel(panel)['policies']['m1-prior']
    arm = row['sol']
    assert arm['complete_pairs'] == 9
    endpoint = arm['forfeit_endpoint']
    assert endpoint['illegal_mirrors'] == 1
    assert endpoint['illegal_failure_rate'] == .05
    assert endpoint['scored_pairs'] == 10
    # Offset3 producer first pair was4/4. Replace flip1 with-1:
    # policy-minus-Sol pair = -(4 + -1)/2 = -1.5, not -2.5.
    assert endpoint['paired_signed_levels']['mean'] == pytest.approx(-8.25)
    assert row['comparison_endpoint'] == 'forfeit_endpoint'


def test_no_failures_preserves_score(tmp_path):
    panel, _, _ = amended(tmp_path, failure=False)
    arm = readout.analyze_panel(panel)['policies']['m1-prior']['sol']
    assert arm['forfeit_endpoint']['paired_signed_levels'] == arm['paired_signed_levels']


def test_infra_failure_blocks_forfeit_not_silently_imputed(tmp_path):
    panel, path, report = amended(tmp_path)
    del report['mirrors'][1]['failure']
    report['mirrors'][1]['error'] = 'TimeoutError: provider'
    path.write_text(json.dumps(report))
    endpoint = readout.analyze_panel(panel)['policies']['m1-prior']['sol']['forfeit_endpoint']
    assert endpoint['status'] == 'blocked'
    assert endpoint['paired_signed_levels'] is None
    assert endpoint['illegal_mirrors'] == 0


def test_unknown_protocol_refuses(tmp_path):
    panel, path, report = amended(tmp_path)
    report['config']['failure_protocol'] = 'retry-until-success'
    path.write_text(json.dumps(report))
    with pytest.raises(readout.PanelReadoutError, match='unknown failure protocol'):
        readout.analyze_panel(panel)


def test_stopped_slots_are_not_counted_as_illegal_losses(tmp_path):
    panel, path, report = amended(tmp_path)
    row = report['mirrors'][2]
    row.update(complete=False, status='not_run', error='failure ceiling', calls=[], events=[])
    row.pop('signed_levels')
    path.write_text(json.dumps(report))
    endpoint = readout.analyze_panel(panel)['policies']['m1-prior']['sol']['forfeit_endpoint']
    assert endpoint['illegal_mirrors'] == 1
    assert endpoint['unattempted_mirrors'] == 1
    assert endpoint['scored_pairs'] == 9
    assert endpoint['status'] == 'partial'


def test_failure_receipt_wrong_team_is_not_a_model_forfeit(tmp_path):
    panel, path, report = amended(tmp_path)
    report['mirrors'][1]['failure']['seat'] = 2
    report['mirrors'][1]['events'][0]['seat'] = 2
    path.write_text(json.dumps(report))
    endpoint = readout.analyze_panel(panel)['policies']['m1-prior']['sol']['forfeit_endpoint']
    assert endpoint['status'] == 'blocked'
    assert endpoint['paired_signed_levels'] is None
