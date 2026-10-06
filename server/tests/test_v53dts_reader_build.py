"""Outcome-blind checks of the lane instance and unchanged estimator gates."""
import ast
import hashlib
import importlib.util
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def load_builder():
    spec = importlib.util.spec_from_file_location('v53_builder', SCRIPTS / 'build_v53dts_reader.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def functions(source):
    return {node.name: ast.dump(node, include_attributes=False)
            for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}


def test_primary_and_metadata_algorithms_unchanged():
    old = functions((SCRIPTS / 'v52ec_reader.py').read_text())
    new = functions(load_builder().build())
    for name in ('pool', 'classify', 'describe_pool', 'arm_levels',
                 'preflight_paired_windows', 'attach_five_window_summaries'):
        assert new[name] == old[name], name


def test_frozen_lane_configuration_and_embedded_helper():
    source = load_builder().build()
    assert (SCRIPTS / 'v53dts_reader.py').read_text() == source
    namespace = {'__file__': str(SCRIPTS / 'v53dts_reader.py'), '__name__': 'test_reader'}
    exec(compile(source, 'v53dts_reader.py', 'exec'), namespace)
    assert namespace['HOST_SEEDS']['cloud'] == (
        53060910, 53160910, 53260910, 53360910, 53460910)
    assert namespace['PREFIXES'] == ('PVSEARCH-r38dts-v53dts', 'PVSEARCH-r38-v53dts')
    assert hashlib.sha256(namespace['CONFIGS'].read_bytes()).hexdigest() == namespace['CONFIG_SHA']
    assert callable(namespace['observe_doomed_throw'])
    assert 'doomed_throw_mechanism=dict' in source
    assert "observe_doomed_throw(item['doomed_throw'], shard" in source
    assert 'activation=dict(' not in source
