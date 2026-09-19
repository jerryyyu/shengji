import json
import pytest

from shengji.train.policy_world_compare import compare


def write_run(path, worlds, values):
    path.mkdir()
    recipe = dict(schema='policy-world-duel-v1', seed0=10, deals=len(values),
                  checkpoint_sha256='a'*64, worlds=worlds, cap=4000, control='mc-smart4',
                  control_effective={'worlds': 4}, policy={'mode': 'policy', 'worlds': worlds},
                  decision_timeout_seconds=300, source_git_sha='git', harness_sha256='h',
                  policy_module_sha256='p', runtime={'python': 'same'})
    (path/'recipe.json').write_text(json.dumps(recipe))
    (path/'summary.json').write_text(json.dumps(dict(errors=[], complete=len(values),
        expected=len(values), mean_utility=sum(values)/len(values))))
    (path/'pairs.jsonl').write_text('\n'.join(json.dumps(dict(seed=10+i, utility=v,
        mirrors=[v, v], error=None, timeout=False)) for i,v in enumerate(values)))


def test_paired_not_independent_intervals(tmp_path):
    a,b = tmp_path/'a', tmp_path/'b'
    write_run(a, 4, [-2.,0.,2.]); write_run(b,16,[-1.5,.5,2.5])
    result = compare(a,b)
    assert result['paired_delta'] == .5
    assert result['ci95'] == [.5,.5]


@pytest.mark.parametrize('field,value', [('control','mc-lcb'),('source_git_sha','changed'),
                                        ('checkpoint_sha256','b'*64),('seed0',11)])
def test_recipe_drift_refuses(tmp_path, field, value):
    a,b = tmp_path/'a', tmp_path/'b'
    write_run(a,4,[0.,1.]); write_run(b,16,[0.,1.])
    p=b/'recipe.json'; r=json.loads(p.read_text()); r[field]=value; p.write_text(json.dumps(r))
    with pytest.raises(ValueError): compare(a,b)


@pytest.mark.parametrize('mutation', ['duplicate', 'timeout', 'mirror', 'missing'])
def test_invalid_pairs_refuse(tmp_path, mutation):
    a,b = tmp_path/'a', tmp_path/'b'
    write_run(a,4,[0.,1.]); write_run(b,16,[0.,1.])
    p=b/'pairs.jsonl'; rows=[json.loads(l) for l in p.read_text().splitlines()]
    if mutation=='duplicate': rows.append(rows[0])
    if mutation=='timeout': rows[0]['timeout']=True
    if mutation=='mirror': rows[0]['mirrors']=[1.,1.]
    if mutation=='missing': rows.pop()
    p.write_text('\n'.join(json.dumps(r) for r in rows))
    with pytest.raises(ValueError): compare(a,b)
