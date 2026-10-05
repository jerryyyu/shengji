import json
import hashlib

import pytest

from scripts import production_llm_panel_readout as reader
from test_benchmark_failure_readout import amended


def _difference(result):
    return next(row for row in result['row_differences']
                if row['left'] == 'smv3-pv' and row['right'] == 'm1-prior')


def test_mixed_legacy_and_recovery_contrast_keeps_failed_pair(tmp_path):
    panel, _, _ = amended(tmp_path)
    result = reader.analyze_panel(panel)
    legacy = result['policies']['smv3-pv']['sol']
    assert legacy['forfeit_endpoint']['paired_signed_levels'] == legacy['paired_signed_levels']
    contrast = _difference(result)
    assert contrast['sol']['count'] == 9
    alternate = contrast['forfeit_endpoint']['sol']
    assert alternate['matched_seeds'] == list(range(10))
    assert alternate['paired_signed_levels']['count'] == 10
    assert alternate['paired_signed_levels']['mean'] == pytest.approx(2.75)
    assert alternate['status'] == 'complete'


def test_legacy_illegality_is_not_retroactively_recoded(tmp_path):
    panel, _, report = amended(tmp_path)
    path = panel['smv3-pv'] / 'result.json'
    legacy = json.loads(path.read_text())
    legacy['mirrors'][1] = report['mirrors'][1]
    path.write_text(json.dumps(legacy))
    result = reader.analyze_panel(panel)
    endpoint = result['policies']['smv3-pv']['sol']['forfeit_endpoint']
    assert endpoint['status'] == 'blocked'
    assert endpoint['paired_signed_levels'] is None
    contrast = _difference(result)['forfeit_endpoint']['sol']
    assert contrast['status'] == 'blocked'
    assert contrast['paired_signed_levels'] is None


def test_pending_slots_are_excluded_not_imputed_and_label_partial(tmp_path):
    panel, path, report = amended(tmp_path)
    pending = report['mirrors'][2]
    pending.pop('signed_levels')
    pending.update(complete=False, status='not_run', calls=[], events=[])
    path.write_text(json.dumps(report))
    alternate = _difference(reader.analyze_panel(panel))['forfeit_endpoint']['sol']
    assert alternate['status'] == 'partial'
    assert alternate['matched_seeds'] == [0, *range(2, 10)]
    assert alternate['paired_signed_levels']['count'] == 9
    assert alternate['right_unattempted_mirrors'] == 1


def test_each_campaign_root_binding_checked_not_just_first(tmp_path):
    panel, _, _ = amended(tmp_path)
    # One recovery row in a separate campaign with a wrong root source pin.
    recovery = tmp_path / 'recovery'
    recovery.mkdir()
    old = panel['m1-prior']
    new = recovery / 'm1-prior'
    old.rename(new)
    panel['m1-prior'] = new
    roots = recovery / 'roots'
    roots.mkdir()
    (roots / 'result.json').write_text('{}')
    (recovery / 'config.json').write_text(json.dumps({
        'schema': 'sol-six-row-recovery-v1', 'rows': list(reader.POLICIES[3:]),
        'seeds': list(range(10)), 'prepared_roots': str(roots),
        'prepared_roots_sha256': '0' * 64,
    }))
    with pytest.raises(reader.PanelReadoutError, match='source SHA mismatch'):
        reader.analyze_panel(panel)


def test_prior_three_and_recovery_six_share_authenticated_roots(tmp_path):
    panel, _, _ = amended(tmp_path)
    roots = tmp_path / 'prepared'
    roots.mkdir()
    sample = json.loads((panel['smv3-pv'] / 'result.json').read_text())
    raw = json.dumps({'roots': sample['roots']}).encode()
    (roots / 'result.json').write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    for name, policies, schema in (
        ('prior', reader.POLICIES[:3], 'sol-nine-policy-campaign-v2'),
        ('recovery', reader.POLICIES[3:], 'sol-six-row-recovery-v1'),
    ):
        campaign = tmp_path / name
        campaign.mkdir()
        (campaign / 'config.json').write_text(json.dumps({
            'schema': schema,
            'rows': list(reader.POLICIES if name == 'prior' else reader.POLICIES[3:]),
            'seeds': list(range(10)), 'prepared_roots': str(roots),
            'prepared_roots_sha256': digest,
        }))
        for policy in policies:
            source = panel[policy]
            target = campaign / policy
            source.rename(target)
            panel[policy] = target
            path = target / 'result.json'
            report = json.loads(path.read_text())
            report['config']['prepared_roots_from']['result_sha256'] = digest
            report['prepared_roots']['result_sha256'] = digest
            path.write_text(json.dumps(report))
    result = reader.analyze_panel(panel)
    assert result['panel_size'] == 9
    assert result['prepared_roots']['source_result_sha256'] == digest
    assert _difference(result)['forfeit_endpoint']['sol']['paired_signed_levels']['mean'] \
        == pytest.approx(2.75)
