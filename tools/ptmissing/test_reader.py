import copy
import importlib.util
from pathlib import Path

import pytest
from shengji.luna import benchmark_terminal as validator

spec = importlib.util.spec_from_file_location('ptmissing', Path(__file__).with_name('reader.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def fixture(position=2):
    seeds = list(range(10))
    seeds[position] = 142060913
    roots = {str(s): 'a'*64 for s in seeds}
    config = dict(seeds=seeds, models=['sol'], information=['perfect'],
                  failure_protocol='preserve-model-illegal-v1', illegal_failure_limit=8,
                  policy='release46-pv', baseline_recipe=dict(benchmark_id='release46-pv', policy='release46-pv', play_only=True),
                  prepared_roots_from=dict(result_sha256='b'*64, root_hashes=roots))
    rows=[]
    for i,s in enumerate(seeds):
        for flip in (0,1):
            row=dict(schema='w32-llm-benchmark-mirror-v1',key=f'sol-perfect-seed{s}-flip{flip}',
                     arm='sol-perfect',model='sol',information='perfect',seed=s,flip=flip,complete=i<position)
            if i<position: row['signed_levels']=i+1
            elif i==position and flip==0:
                row['error']='private error'
                row['calls']=[{'error':'CodexTurnTransportError: Codex trace event forbidden'}]
            else: row.update(status='not_run',calls=[],events=[])
            rows.append(row)
    report=dict(schema='w32-llm-benchmark-v1',mode='run',config=config,mirrors=rows,roots=roots,
                prepared_roots=dict(result_sha256='b'*64,root_hashes=roots))
    return report,copy.deepcopy(config),copy.deepcopy(rows[2*position])


def test_counts_and_sign_use_only_complete_pairs_without_mutation():
    report,config,missing=fixture()
    before=copy.deepcopy(report)
    out=p.analyze(report,config,missing,validator)
    assert report==before
    assert out['policy_minus_pt_mean']==-1.5
    assert out['complete_pair_count']==2
    assert out['accounting']=={'complete':4,'unattempted':15,'adjudicated-missing':1,'retained-model-failure':0}
    assert out['quality']=='INCOMPLETE'
    assert 'private' not in str(out)
    assert set(out['excluded_pair_seeds'])==set(config['seeds'][2:])


def test_first_mirror_failure_has_no_survivor_estimate():
    out=p.analyze(*fixture(0),validator)
    assert out['complete_pair_count']==0
    assert out['policy_minus_pt_mean'] is None and out['conditional_deal_cluster_ci95'] is None


@pytest.mark.parametrize('fault',['second-failure','duplicate','missing','config','roots','score','before-stop','after-stop','adjudicated-score','binding','identity'])
def test_every_nonadjudicated_fault_stays_fatal(fault):
    report,config,missing=fixture()
    rows=report['mirrors']
    if fault=='second-failure': rows[0].update(complete=False,error='other')
    if fault=='duplicate': rows[-1]=copy.deepcopy(rows[0])
    if fault=='missing': rows.pop()
    if fault=='config': report['config']['policy']='other'
    if fault=='roots': report['roots']={}
    if fault=='score': rows[0]['signed_levels']=float('nan')
    if fault=='before-stop':
        rows[0].pop('signed_levels'); rows[0].update(complete=False,status='not_run')
    if fault=='after-stop': rows[-1].update(complete=True,signed_levels=1)
    if fault=='adjudicated-score': rows[4]['signed_levels']=0; missing=copy.deepcopy(rows[4])
    if fault=='binding': missing['error']='different'
    if fault=='identity': rows[0]['flip']=True
    with pytest.raises(ValueError): p.analyze(report,config,missing,validator)


def test_unpaired_completed_mirror_is_not_scored():
    report,config,missing=fixture()
    # The authorized missing key is flip0, so its flip1 is unattempted and
    # cannot become an orphan score after the stop.
    report['mirrors'][5].update(complete=True,signed_levels=-3)
    with pytest.raises(ValueError): p.analyze(report,config,missing,validator)


def test_duplicate_and_nonfinite_json_refuse():
    for raw in (b'{"a":1,"a":2}', b'{"a":NaN}'):
        with pytest.raises(ValueError): p.decode(raw)


@pytest.mark.parametrize('fault',[None,'hold','result-pin','output-exists'])
def test_fresh_process_sealed_files_to_output(tmp_path,fault):
    import hashlib
    import json
    import subprocess
    import sys
    root=tmp_path/'root'; root.mkdir(); (root/'benchmark').mkdir()
    packet=tmp_path/'packet'; packet.mkdir()
    source=tmp_path/'source'; source.mkdir()
    output=tmp_path/'output'
    report,config,missing=fixture()
    paths=[(root/'terminal.json',{}),(root/'benchmark/result.json',report),
           (root/'benchmark/mirror-sol-perfect-142060913-0.json',missing),(packet/'expected-config.json',config)]
    hashes=[]
    for path,value in paths:
        raw=json.dumps(value).encode(); path.write_bytes(raw); hashes.append(hashlib.sha256(raw).hexdigest())
    local=Path(__file__).resolve().parents[2]/'server'
    pins={}
    for name in p.SOURCE_PINS:
        dest=source/name; dest.parent.mkdir(parents=True,exist_ok=True)
        raw=(local/name).read_bytes(); dest.write_bytes(raw)
        pins[name]=hashlib.sha256(raw).hexdigest()
    if fault=='hold': (root/'HOLD').touch()
    if fault=='output-exists': output.mkdir()
    if fault=='result-pin': hashes[1]='0'*64
    code=f'''import importlib.util
from pathlib import Path
s=importlib.util.spec_from_file_location('reader',{str(Path(p.__file__).resolve())!r})
m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
m.ROOT=Path({str(root)!r}); m.PACKET=Path({str(packet)!r}); m.SOURCE=Path({str(source)!r}); m.OUTPUT=Path({str(output)!r})
m.PRODUCER_PIDS=(); m.SOURCE_PINS={pins!r}
m.TERMINAL_SHA,m.RESULT_SHA,m.MIRROR_SHA,m.CONFIG_SHA={hashes!r}
m.run()
'''
    done=subprocess.run([sys.executable,'-B','-c',code],capture_output=True)
    assert done.stdout==b''
    if fault:
        assert done.returncode!=0
        assert not (output/'result.json').exists()
        assert b'private error' not in done.stderr
    else:
        assert done.returncode==0,done.stderr.decode()
        result=json.loads((output/'result.json').read_text())
        assert result['policy_minus_pt_mean']==-1.5
        again=subprocess.run([sys.executable,'-B','-c',code],capture_output=True)
        assert again.returncode!=0
        assert json.loads((output/'result.json').read_text())==result
