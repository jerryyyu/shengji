import hashlib
from pathlib import Path

import numpy as np
import pytest

from shengji.eval import s11_model as module
from shengji.eval.s11_collection import collect_s11_fixture
from shengji.eval.s11_public_view import public_s11_fixture
from test_pv_search_serving import package
from test_s11_public_view import trajectory


@pytest.fixture
def frozen(tmp_path, package):
    original, pin = package
    path = tmp_path / 'model.npz'
    path.write_bytes(Path(original).read_bytes())
    path.chmod(0o400)
    source = hashlib.sha256((Path(original).parent / 'joint.pt').read_bytes()).hexdigest()
    return path, dict(sha256=pin, source_checkpoint_sha256=source)


def test_lazy_checked_loader_once_independent_rng_counters_and_no_reload(frozen, monkeypatch):
    path, pins = frozen
    real = module.pv.make_pv_search_bot
    calls = []
    def spy(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)
    monkeypatch.setattr(module.pv, 'make_pv_search_bot', spy)
    build = module.make_s11_model_factory(path, **pins)
    assert not calls
    first = build()
    # From now on both canonical constructor and file hashes must stay unused.
    monkeypatch.setattr(module.pv, 'make_pv_search_bot', lambda *_a, **_k: pytest.fail('reload'))
    monkeypatch.setattr(module.pv, 'file_sha256', lambda *_: pytest.fail('rehash'))
    second = build()
    assert len(calls) == 1
    assert first is not second and first.sampler is not second.sampler
    assert first._refusals is not second._refusals
    assert first.evaluator is not second.evaluator
    assert first.sampler.rng.getstate() == second.sampler.rng.getstate()
    first.sampler.rng.random()
    first.evaluator.calls = 99
    assert second.evaluator.calls == 0 and build().evaluator.calls == 0
    assert first.sampler.rng.getstate() != second.sampler.rng.getstate()
    assert first.evaluator.model._weights is second.evaluator.model._weights
    assert all(not w.flags.writeable for w in first.evaluator.model._weights.values())


def test_real_exported_synthetic_model_through_s11_capture(frozen, trajectory):
    path, pins = frozen
    build = module.make_s11_model_factory(path, **pins)
    fixture = public_s11_fixture(trajectory, 98, root_id='synthetic-model')
    result = collect_s11_fixture(build, fixture, seed=0, fill_seed=0)
    assert result['recipe']['checkpoint_sha256'] == pins['sha256']
    assert result['encoder_version'] == 2 and result['report']['status'] == 'valid'
    assert len(result['worlds']) == 64
    assert np.isfinite(result['value_capture']['value_matrix']).all()
    # Scientific equality to the same canonical factory constructed per call.
    def ordinary():
        return module.pv.make_pv_search_bot(str(path), sha256=pins['sha256'],
            seed=0, worlds=64, candidates=8, cap=4000, batch_size=128,
            refusal_constraints=True, admission_diversity=True,
            tiebreak_points=True, lead_anchor=True)
    control = collect_s11_fixture(ordinary, fixture, seed=0, fill_seed=0)
    for key in ('worlds', 'policy_capture', 'value_capture', 'report', 'tape_receipt'):
        assert result[key] == control[key]


@pytest.mark.parametrize('which', ['export', 'source'])
def test_wrong_identity_poisoned_no_implicit_load_retry(frozen, which, monkeypatch):
    path, pins = frozen
    pins['sha256' if which == 'export' else 'source_checkpoint_sha256'] = 'a' * 64
    build = module.make_s11_model_factory(path, **pins)
    with pytest.raises((ValueError, module.pv.PVSearchPolicyError)):
        build()
    monkeypatch.setattr(module.pv, 'make_pv_search_bot', lambda *_a, **_k: pytest.fail('retry'))
    with pytest.raises(ValueError, match='explicit disposition'):
        build()


def test_file_drift_after_load_refuses_even_with_cached_weights(frozen):
    path, pins = frozen
    build = module.make_s11_model_factory(path, **pins)
    build()
    path.chmod(0o600)
    path.write_bytes(path.read_bytes() + b' ')
    path.chmod(0o400)
    with pytest.raises(ValueError, match='export changed'):
        build()


def test_mutable_or_symlink_package_refuses_before_loading(frozen, monkeypatch):
    path, pins = frozen
    monkeypatch.setattr(module.pv, 'make_pv_search_bot', lambda *_a, **_k: pytest.fail('load'))
    link = path.with_name('alias.npz')
    link.symlink_to(path)
    with pytest.raises(ValueError):
        module.make_s11_model_factory(link, **pins)
    path.chmod(0o600)
    with pytest.raises(ValueError, match='frozen regular'):
        module.make_s11_model_factory(path, **pins)


def test_search_mean_export_is_not_the_outcome_model(tmp_path, package):
    from scripts.export_cwv_numpy import export_cwv_numpy
    original, _ = package
    checkpoint = Path(original).parent / 'joint.pt'
    path = tmp_path / 'search-mean.npz'
    export_cwv_numpy(checkpoint, path, value_head='search-mean')
    pin = hashlib.sha256(path.read_bytes()).hexdigest()
    path.chmod(0o400)
    build = module.make_s11_model_factory(path, sha256=pin,
        source_checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match='model/export identity'):
        build()


def test_change_during_canonical_load_never_returns_bot(frozen, monkeypatch):
    path, pins = frozen
    real = module.pv.make_pv_search_bot
    def change(*args, **kwargs):
        bot = real(*args, **kwargs)
        path.chmod(0o600)
        path.write_bytes(path.read_bytes() + b' ')
        path.chmod(0o400)
        return bot
    monkeypatch.setattr(module.pv, 'make_pv_search_bot', change)
    build = module.make_s11_model_factory(path, **pins)
    with pytest.raises(ValueError, match='changed during loading'):
        build()
