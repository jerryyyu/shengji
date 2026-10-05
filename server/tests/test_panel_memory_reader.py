import copy
import json
from pathlib import Path

import pytest

from scripts import production_llm_panel_readout as reader
from test_production_llm_panel_readout import _panel, SEEDS, ROOTS, SOURCE_SHA
from test_benchmark_failure_readout import amended


def inputs(panel):
    reports = {key: json.loads((path / 'result.json').read_bytes()) for key, path in panel.items()}
    contexts = {key: dict(seeds=SEEDS, source_result_sha256=SOURCE_SHA, root_hashes=ROOTS)
                for key in reader.POLICIES}
    return reports, contexts


@pytest.mark.parametrize('mixed', [False, True])
def test_same_data_exact_arithmetic_parity_without_filesystem(tmp_path, monkeypatch, mixed):
    panel = amended(tmp_path)[0] if mixed else _panel(tmp_path)
    expected = reader.analyze_panel(panel)
    for row in expected['policies'].values():
        row['identity']['directory'] = None
    reports, contexts = inputs(panel)
    original = copy.deepcopy((reports, contexts))
    def forbidden(*args, **kwargs):
        pytest.fail('in-memory arithmetic touched filesystem')
    for name in ('read_bytes', 'read_text', 'open', 'exists', 'is_file', 'is_dir', 'resolve'):
        monkeypatch.setattr(Path, name, forbidden)
    actual = reader.analyze_panel_reports(reports, contexts)
    assert actual == expected
    assert (reports, contexts) == original


@pytest.mark.parametrize('kind', ['missing-report', 'missing-context', 'none-report',
                                  'wrong-seeds', 'wrong-root', 'missing-mirror', 'bad-score'])
def test_in_memory_reader_has_no_partial_file_fallback(tmp_path, kind):
    reports, contexts = inputs(_panel(tmp_path))
    key = reader.POLICIES[0]
    if kind == 'missing-report':
        del reports[key]
    elif kind == 'missing-context':
        del contexts[key]
    elif kind == 'none-report':
        reports[key] = None
    elif kind == 'wrong-seeds':
        contexts[key]['seeds'] = list(reversed(SEEDS))
    elif kind == 'wrong-root':
        contexts[key]['source_result_sha256'] = '0' * 64
    elif kind == 'missing-mirror':
        reports[key]['mirrors'].pop()
    else:
        reports[key]['mirrors'][0]['signed_levels'] = float('nan')
    with pytest.raises(ValueError):
        reader.analyze_panel_reports(reports, contexts)
