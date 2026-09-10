import io
import json
import os
from pathlib import Path
import selectors
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.train.cwv_shortlist import CWVShortlistBot
from shengji.train.r4_inference_service import serve
from shengji.train.r4_mixture_policy import R4MixtureRankBot
from shengji.train.r4_runtime_client import R4RuntimeClient
from shengji.train.world_mixture_fit import reweighted_consumer_means


def test_actor_only_service_handles_multiple_requests_without_reload():
    requests = [{'request_id': i, 'actor': {'visible': i}} for i in (1, 2)]
    calls = []
    def predict(actor):
        calls.append(actor)
        return {'actor_sha256': str(actor['visible']), 'arms': {}}
    output = io.StringIO()
    serve(predict, {'model': 'same'}, io.StringIO(''.join(json.dumps(r)+'\n' for r in requests)), output)
    replies = [json.loads(line) for line in output.getvalue().splitlines()]
    assert replies[0] == {'ready': True, 'identity': {'model': 'same'}}
    assert calls == [{'visible': 1}, {'visible': 2}]
    assert [r['request_id'] for r in replies[1:]] == [1, 2]


def test_service_refuses_hidden_capture_envelope_before_inference():
    raw = json.dumps({'request_id': 1, 'actor': {}, 'worlds': ['privileged']})+'\n'
    def never(_):
        pytest.fail('extra fields reached inference')
    with pytest.raises(ValueError, match='actor-only inference request required'):
        serve(never, {}, io.StringIO(raw), io.StringIO())


def test_partial_response_times_out_instead_of_blocking_readline():
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, 'rb', buffering=0)
    client = object.__new__(R4RuntimeClient)
    client.process = SimpleNamespace(stdout=reader)
    client.selector = selectors.DefaultSelector()
    client.selector.register(reader, selectors.EVENT_READ)
    client.timeout, client.pending = .01, b''
    os.write(write_fd, b'{"partial":')
    try:
        with pytest.raises(TimeoutError, match='response deadline exceeded'):
            client._read()
    finally:
        client.selector.close()
        reader.close()
        os.close(write_fd)


def test_rank_bot_fits_without_values_and_uses_fitted_weights_in_real_wrapper(monkeypatch):
    import shengji.train.r4_mixture_policy as module
    actor = SimpleNamespace(sha256=lambda: 'actor')
    monkeypatch.setattr(module, 'actor_for_round', lambda *args: actor)
    matrix = np.array([[0, 10], [0, 10], [0, -10], [0, -10]])
    calls = []
    class Evaluator:
        def score(self, *args, **kwargs):
            calls.append('values')
            return matrix.ravel()
    class Client:
        archive_server = Path('/unused')
        def predict(self, observation):
            assert observation is actor and not calls
            return {'inference_wall_s': 0, 'arms': {'synthetic-primary': {'ownership': {
                'count_probabilities': [{'card': 'S2', 'receiver': 'seat-relative-1',
                                        'count_probability_ppb': [0, 1000000000, 0]}]}}}}
    def ordinary(self, rnd, seat, actions, worlds):
        self.evaluator.score([], seat)
        return np.zeros(2)
    monkeypatch.setattr(CWVShortlistBot, '_means', ordinary)
    evaluator = Evaluator()
    bot = R4MixtureRankBot(evaluator, client=Client(), model_arm='synthetic-primary')
    worlds = [([[], ['S2'], [], []], [])]*2 + [([[], [], [], []], [])]*2
    weighted = bot._means(None, 0, [['C2'], ['D2']], worlds)
    fit = bot.last_mixture['fit']
    assert weighted[1] > 9.9
    assert np.array_equal(weighted, reweighted_consumer_means(matrix, fit['weights'], [0, 0]))
    assert bot.evaluator is evaluator
    assert bot.last_mixture['mc_weighted'] is False
    assert bot.bury_arm == 'hybrid'


def test_ordinary_arm_never_constructs_actor_or_calls_model(monkeypatch):
    import shengji.train.r4_mixture_policy as module
    def never(*args):
        pytest.fail('ordinary arm touched inference')
    monkeypatch.setattr(module, 'actor_for_round', never)
    sentinel = np.array([.1, .2])
    monkeypatch.setattr(CWVShortlistBot, '_means', lambda *args: sentinel)
    bot = R4MixtureRankBot(object(), client=None, model_arm='ordinary')
    assert bot._means(None, 0, [], []) is sentinel


def test_rank_bot_restores_evaluator_if_original_consumer_fails(monkeypatch):
    import shengji.train.r4_mixture_policy as module
    monkeypatch.setattr(module, 'actor_for_round', lambda *args: object())
    client = SimpleNamespace(archive_server='/unused', predict=lambda actor: {'arms': {
        'synthetic-primary': {'ownership': {'count_probabilities': [
            {'card': 'S2', 'receiver': 'seat-relative-1', 'count_probability_ppb': [1e9, 0, 0]}]}}}})
    def fail(*args):
        raise RuntimeError('consumer failed')
    monkeypatch.setattr(CWVShortlistBot, '_means', fail)
    evaluator = object()
    bot = R4MixtureRankBot(evaluator, client=client, model_arm='synthetic-primary')
    with pytest.raises(RuntimeError, match='consumer failed'):
        bot._means(None, 0, [['C2']], [([[], [], [], []], [])]*2)
    assert bot.evaluator is evaluator
