"""The gate consumes the extractor's attempted-play replay, including on resume."""
import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

from shengji.ai.belief_numpy import decision_inputs
from shengji.harvest.rebuild import state_for_record
from shengji.train.belief_labels import game_order, iter_decisions
from test_belief_labels import synthetic_cluster

PATH = Path(__file__).parents[1] / 'scripts' / 'unified_value_gate.py'
spec = importlib.util.spec_from_file_location('unified_value_gate', PATH)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def same_inputs(a, b):
    assert a.keys() == b.keys()
    for key in a:
        np.testing.assert_array_equal(a[key], b[key], err_msg=key)


def test_roots_preserve_all_refusals_and_freeze_earlier_frames():
    records = synthetic_cluster(1000, throw_rate=1)
    expected = {}
    for d in iter_decisions(records):
        expected[d.record['source_ref']] = (d.refusals, decision_inputs(d.rnd, d.seat, d.refusals))
    bot = NS()
    held = []
    changed = 0
    for rec, root in gate.iter_gate_roots(records, bot):
        refs, inp = expected[rec['source_ref']]
        assert tuple(bot._refusals.observe(root)) == refs
        same_inputs(decision_inputs(root, rec['seat'], refs), inp)
        held.append((root, copy.deepcopy({k:v for k,v in vars(root).items() if k != 'ordering'})))
        old = decision_inputs(state_for_record(rec), rec['seat'], ())
        changed += not np.array_equal(old['X'], inp['X'])
    assert changed > 0
    assert len({id(root) for root, _ in held}) == len(records)
    for root, before in held:
        assert {k:v for k,v in vars(root).items() if k != 'ordering'} == before


def test_real_gate_loop_preserves_sampler_inputs_and_resume_frames(tmp_path, monkeypatch, capsys):
    from shengji.ai import belief_numpy, cwv_policy, unified_readout_numpy
    from shengji.harvest import legal
    from shengji.train import unified_slots
    records = game_order(synthetic_cluster(1000, throw_rate=1))[:8]
    for rec in records:
        rec['ply'] = len(rec['plays_prefix'])
        rec['outcome'] = {'attacker_points': 80, 'kitty_bonus': 0,
                          'winner_team': 1 - int(rec['setup']['banker']) % 2, 'level_change': 0}
    expected = {}
    for d in iter_decisions(records):
        expected[len(d.record['plays_prefix'])] = (d.refusals, decision_inputs(d.rnd, d.seat, d.refusals))
    seen = []
    class Bot:
        worlds = 64
        belief_worlds = world_history_legal = refusal_constraints = True
        sampler = NS(rng=NS(seed=lambda x: None))
        evaluator = NS(checkpoint_sha256='f4f4127ec0c8821b4aa07f7d651a4258c696f97a874707da2c78ad26c0c9b9fd',
                       support=np.arange(201), encoder=lambda r,s: 0,
                       probabilities=lambda xs: np.ones((len(xs),201))/201)
        def _worlds(self, root, seat):
            ply = sum(len(t.plays) for t in root.history) + len(root.trick.plays)
            refs, inp = expected[ply]
            assert tuple(self._refusals.observe(root)) == refs
            same_inputs(decision_inputs(root,seat,self._refusals.refusals),inp)
            seen.append(ply)
            self._last_sampling = {'belief_fallback': 0}
            return [([list(h) for h in root.hands], list(root.buried))]*64, 64
        def scores(self, root, seat, actions, worlds):
            return np.zeros((1,len(actions)))
    name = 'pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-rcec-whl-whd-wht-bw-tb-ele-elt-elm-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-els1600-xf7-xfcompactlevel-r12e81e0c-bury-hybrid-bwv-bbw-7a9a430fe690-sc8'
    adapter = tmp_path/'adapter.py'
    adapter.write_text('')
    original = gate.importlib.util.spec_from_file_location
    def load(name_, path):
        if str(path) != str(adapter):
            return original(name_,path)
        class Loader:
            def create_module(self,spec): return None
            def exec_module(self,module):
                module.D = NS(_parse_env=lambda xs: {},variant_factory=lambda env:(name,lambda seed:Bot()))
        return importlib.util.spec_from_loader(name_,Loader())
    monkeypatch.setattr(gate.importlib.util,'spec_from_file_location',load)
    model_seen = []
    def card_states(inp, history):
        same_inputs(inp, expected[len(model_seen)][1])
        model_seen.append(inp)
        return None, None
    model = NS(package_sha256='a'*64,trunk=NS(encode_history=lambda inp:None),
               card_states=card_states,decision_cache=lambda q,g:None,
               leaf_value_probs=lambda c,p,s:np.ones((len(p),201))/201,
               leaf_reply_logits=lambda c,p,s:np.zeros((len(p),54)))
    monkeypatch.setattr(unified_readout_numpy,'load_unified_readout_numpy',lambda *a:model)
    monkeypatch.setattr(belief_numpy,'PREP_SECONDS',belief_numpy.PREP_SECONDS)
    monkeypatch.setattr(cwv_policy,'afterstate',lambda root,*a,**kw:root)
    def features(frame,root):
        scalars=np.zeros(12);scalars[8+(root.turn-frame.seat)%4]=1
        return np.zeros((9,54)),scalars
    monkeypatch.setattr(unified_slots,'leaf_features',features)
    # Keep legal-listing cost out of a replay/consumer contract test.
    monkeypatch.setattr(legal,'enumerate_legal',lambda root,seat,cap,must_include:NS(actions=[must_include[0],['BJ']]))
    view=tmp_path/'view';(view/'shards').mkdir(parents=True)
    (view/'manifest.json').write_text(json.dumps({'shards':[{'cluster':0}]}))
    (view/'shards'/'cluster-000000.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    def run(out,limit, words=""):
        model_seen.clear()
        gate.main([str(out),'--view',str(view),'--adapter',str(adapter),'--words',words,
                   '--pkg','unused','--sha','a'*64,'--limit',str(limit)])
    full=tmp_path/'full.jsonl';run(full,0)
    seen.clear()
    partial=tmp_path/'partial.jsonl';run(partial,2);run(partial,0)
    assert seen == list(range(8))
    def rows(path):
        return [{k:v for k,v in json.loads(line).items() if k!='secs'}
                for line in path.read_text().splitlines()]
    assert rows(full)==rows(partial)
    monkeypatch.syspath_prepend(str(PATH.parent))
    import unified_value_gate_read as reader
    chosen = tmp_path / 'chosen.json'
    chosen.write_text(json.dumps({'clusters': [0]}))
    result_path = tmp_path / 'read.json'
    capsys.readouterr()
    reader.main([str(result_path), str(chosen), str(full)])
    summary = json.loads(capsys.readouterr().out)
    (tmp_path / 'read.out').write_text(json.dumps(summary) + '\n')
    result = json.loads(result_path.read_text())
    assert result['validity']['verdict'] == 'VALID'
    assert result['value']['gate']['verdict'] == 'PASS'
    assert result['reply']['gate']['verdict'] == 'PASS'
    assert summary['value_gate'] == result['value']['gate']
    assert summary['reply_gate'] == result['reply']['gate']
    assert summary['replay'] == reader.REPLAY
    # The lane invokes the reader in isolation, outside the source checkout.
    foreign = tmp_path / 'foreign'
    foreign.mkdir()
    for module in ('shengji', 'expert_labels', 'validity', 'unified_value_gate'):
        (foreign / (module + '.py')).write_text('raise RuntimeError("wrong checkout imported")\n')
    for mode in ('-I', '-P'):
        cli_out = tmp_path / f'cli-{mode}.json'
        cli = subprocess.run([sys.executable, mode, str(PATH.with_name('unified_value_gate_read.py')),
                              str(cli_out), str(chosen), str(full)], cwd=foreign,
                             env={**os.environ, 'PYTHONPATH': str(foreign)},
                             capture_output=True, text=True)
        assert cli.returncode == 0, cli.stdout + cli.stderr
        assert json.loads(cli_out.read_text()) == result
        assert json.loads(cli.stdout) == summary
    # Cluster coverage alone cannot detect deleted decisions inside a worker file.
    damaged = rows(full)
    del damaged[3]
    lost = tmp_path / 'lost-row.jsonl'
    lost.write_text(''.join(json.dumps(row) + '\n' for row in damaged))
    lost_before = lost.read_bytes()
    with pytest.raises(ValueError, match='row count'):
        reader.main([str(tmp_path / 'lost-read.json'), str(chosen), str(lost)])
    assert not (tmp_path / 'lost-read.json').exists()
    with pytest.raises(ValueError, match='row count'):
        run(lost, 0)
    assert lost.read_bytes() == lost_before
    assert rows(full)[-1]['rows'] == len(rows(full)[:-1]) == 8
    for count in (None, True, 8.0, -1, 7, 9):
        damaged = rows(full)
        damaged[-1]['rows'] = count
        lost.write_text(''.join(json.dumps(row) + '\n' for row in damaged))
        with pytest.raises(ValueError, match='row count'):
            reader.main([str(tmp_path / 'lost-read.json'), str(chosen), str(lost)])
        with pytest.raises(ValueError, match='row count'):
            run(lost, 0)
    assert not (tmp_path / 'lost-read.json').exists()
    duplicate = rows(full)
    duplicate.insert(1, duplicate[0])
    duplicate[-1]['rows'] += 1
    lost.write_text(''.join(json.dumps(row) + '\n' for row in duplicate))
    lost_before = lost.read_bytes()
    with pytest.raises(ValueError, match='duplicate decision'):
        run(lost, 0)
    assert lost.read_bytes() == lost_before
    invalid_file = tmp_path / 'invalid-worlds.jsonl'
    invalid_rows = rows(full)
    invalid_rows[0]['worlds'] = 63
    invalid_file.write_text(''.join(json.dumps(row) + '\n' for row in invalid_rows))
    reader.main([str(tmp_path / 'invalid-read.json'), str(chosen), str(invalid_file)])
    invalid_summary = json.loads(capsys.readouterr().out)
    assert invalid_summary['validity'] == 'DEV_INVALID'
    assert 'value_gate' not in invalid_summary and 'reply_gate' not in invalid_summary
    with pytest.raises(ValueError, match='already exists'):
        reader.main([str(result_path), 'missing', 'missing'])
    valid = rows(full)[:-1]
    boundary = [dict(copy.deepcopy(valid[2]), ref=f'boundary-{i}') for i in range(100)]
    boundary[0]['belief_fallback'] = 1
    assert reader.validate_rows(boundary, {0})['verdict'] == 'VALID'
    boundary[1]['belief_fallback'] = 1
    assert reader.validate_rows(boundary, {0})['verdict'] == 'DEV_INVALID'
    def no_statistics(*args):
        raise AssertionError('invalid rows reached outcome statistics')
    with monkeypatch.context() as m:
        m.setattr(reader, 'boot', no_statistics)
        mutations = [
            lambda r: r.update(worlds=63),
            lambda r: r.update(belief_fallback=1),
            lambda r: r.pop('belief_fallback'),
            lambda r: r['outcome'].update(level_change=3),
            lambda r: r.update(target=r['target']+1),
            lambda r: r['end'].update(ro_mix=float('nan')),
            lambda r: r.update(adapter='different'),
            lambda r: r['end'].update(ro_lvl=True),
            lambda r: r['reply'][0].update(top4_overlap=99),
        ]
        empty_reply = [dict(r, reply=[]) for r in valid]
        assert reader.analyze(empty_reply, {0})['validity']['verdict'] == 'DEV_INVALID'
        for mutate in mutations:
            invalid = copy.deepcopy(valid)
            mutate(invalid[2])
            result = reader.analyze(invalid, {0})
            assert result['validity']['verdict'] == 'DEV_INVALID'
            assert 'value' not in result and 'reply' not in result
    incomplete = tmp_path / 'incomplete.jsonl'
    incomplete.write_text(''.join(json.dumps(r)+'\n' for r in valid))
    with pytest.raises(ValueError, match='terminal'):
        reader.main([str(tmp_path/'bad.json'), str(chosen), str(incomplete)])
    with pytest.raises(ValueError, match='worker partitions'):
        reader.main([str(tmp_path/'bad.json'), str(chosen), str(full), str(full)])
    chosen.write_text(json.dumps({'clusters': [0, 1]}))
    swapped = []
    for worker in range(2):
        path = tmp_path / f'swapped-{worker}.jsonl'
        records_ = [dict(copy.deepcopy(r), cluster=1-worker, worker=worker, workers=2,
                         ref=f'{worker}-{r["ref"]}') for r in valid]
        records_.append(dict(rows(full)[-1], worker=worker, workers=2, clusters=1))
        path.write_text(''.join(json.dumps(r)+'\n' for r in records_))
        swapped.append(str(path))
    with pytest.raises(ValueError, match='worker cluster coverage'):
        reader.main([str(tmp_path/'bad.json'), str(chosen), *swapped])
    assert not (tmp_path/'bad.json').exists()

    completed_bytes = partial.read_bytes()
    run(partial, 0)
    assert partial.read_bytes() == completed_bytes
    assert rows(full)[2]['reply'] and len(rows(full)[2]['reply'])==2
    stale=tmp_path/'stale.jsonl';stale.write_text(json.dumps({'ref':records[0]['source_ref']})+'\n')
    before=stale.read_bytes()
    with pytest.raises(ValueError,match='incompatible replay'):
        run(stale,0)
    assert stale.read_bytes()==before

    for changed in ('manifest', 'adapter', 'words'):
        manifest = view / 'manifest.json'
        old_manifest, old_adapter = manifest.read_bytes(), adapter.read_bytes()
        if changed == 'manifest':
            manifest.write_text(json.dumps({'shards':[{'cluster':0}], 'source':'different'}))
        if changed == 'adapter':
            adapter.write_text('# different adapter producer\n')
        before = partial.read_bytes()
        with pytest.raises(ValueError, match='incompatible replay or model/input'):
            run(partial, 0, words='changed=1' if changed == 'words' else '')
        assert partial.read_bytes() == before
        manifest.write_bytes(old_manifest)
        adapter.write_bytes(old_adapter)

    model.package_sha256 = 'b'*64
    before = partial.read_bytes()
    with pytest.raises(ValueError, match='incompatible replay or model'):
        run(partial, 0)
    assert partial.read_bytes() == before
