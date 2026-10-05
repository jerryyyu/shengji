"""Build the v52 instance from the reviewed five-window estimator/raw pass.

Prints source for review; never executes the reader or touches outcomes.
"""
import ast
import hashlib
from pathlib import Path

BASE = Path('/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/readers/v50t38_reader.py')
BASE_SHA = '5c18e4422386e1c10d3518a07e1da210422f9201d4ec6533a89bec0bf1a1ac38'
HERE = Path(__file__).resolve().parent


def replace(text, old, new):
    assert text.count(old) == 1, old[:100]
    return text.replace(old, new)


def build():
    raw = BASE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == BASE_SHA
    source = raw.decode()
    body = source[source.index('def analyze('):source.index('\n\ndef main():')]
    start = body.index('        for host, root in roots.items():')
    stop = body.index('        census, cache, receipts, means, seen = {}, {}, [], [], set()')
    body = body[:start] + '''        templates, template_sha = load(CONFIGS)
        need(template_sha == CONFIG_SHA, 'outcome-blind config freeze drift')
        metadata[CONFIGS] = template_sha
        lane_metadata = check_lane(root=roots['cloud'], reservation=reservation, status=status, load=load)
        metadata.update(lane_metadata)
        expected = {}
        for side, prefix in enumerate(PREFIXES):
            for seed in HOST_SEEDS['cloud']:
                config = copy.deepcopy(templates[side])
                config['seed0'] = seed
                expected[f'{prefix}-{seed}'] = config
        paired, checksums = preflight_paired_windows(roots['cloud'], expected,
            seeds=HOST_SEEDS['cloud'], prefixes=PREFIXES, clusters=CLUSTERS, validator=validator)
        entries = [('cloud', seed, pair) for seed, pair in paired]
        metadata.update(checksums)
''' + body[stop:]
    body = replace(body, 'def analyze(cloud_root, *, rc_path=', 'def analyze(cloud_root, *, reservation, status, rc_path=')
    body = replace(body, "        return dict(schema='v50t38-five-window-triage-v1', integrity='PASS',", "        result = dict(schema='v52ec-five-window-triage-v1', integrity='PASS',")
    old_question = next(line for line in body.splitlines() if line.strip().startswith('question='))
    body = replace(body, old_question, "            question='event-complete refusal history versus release38, same package and common MC-LCB control',")
    body = body.replace('five v50t38 windows', 'five v52ec windows')
    body = replace(body, ' common_config_sha256=COMMON_SHA,', '')
    body = replace(body,
        "                observe_activations(item['activations'], shard)",
        "                observe_refusal_max(item['refusal_census'], shard)\n"
        "                observe_activations(item['activations'], shard)")
    body = body.replace('and only if the point is above +0.015; no pooling',
                        'and only if the point is above +0.015 AND CI includes zero; no pooling')
    body += "\n    return attach_five_window_summaries(result, seeds=HOST_SEEDS['cloud'], prefixes=PREFIXES)\n"
    selected = {'need', 'digest', 'helper', 'empty_activations', 'observe_activations',
                'pool', 'classify', 'describe_pool', 'arm_levels'}
    defs = '\n\n'.join(ast.get_source_segment(source, node) for node in ast.parse(source).body
                       if isinstance(node, ast.FunctionDef) and node.name in selected)
    helpers = []
    for filename in ('refusal_readout_summary.py', 'paired_window_metadata.py'):
        text = (HERE.parent / 'shengji/eval' / filename).read_text()
        helpers.extend(ast.get_source_segment(text, node) for node in ast.parse(text).body
                       if isinstance(node, ast.FunctionDef))
    header = '''"""v52ec sealed one-pass reader. Pending independent review; no launch authority.
Reuses the SHA-pinned v50t38 raw pass, health helpers and five-window primary.
Full outcome-blind configs replace the nonexistent legacy pins/admission files.
Caller must independently verify terminal process state and exclusive ownership.
"""
import argparse, copy, hashlib, json, math, re, types
from pathlib import Path
from collections.abc import Iterable, Mapping

HOST_SEEDS = {'cloud': (52060910, 52160910, 52260910, 52360910, 52460910)}
HOST_OF = {'cloud': 'cloud'}
CLUSTERS = 520
PREFIXES = ('PVSEARCH-r38rcec-v52ec', 'PVSEARCH-r38-v52ec')
NAMES = ('pv-search-491ee4bf-w64-k8-div-rc-rcec-tb-la-r3950772a-bury-hybrid-ad86d3fafbbd',
         'pv-search-491ee4bf-w64-k8-div-rc-tb-la-r7092480e-bury-hybrid-5517ddbd7457')
LAUNCHER_SHA = 'd44880a86210dda9d55cb4992ef87a4bfbd8e821ff14af7b7f1881f9d1f030c4'
EXPECTED_SHA = ('c177d5f51ed1bc79fbb24365fe3761e919a3054953a27dfa1832fd80f3df6ce2',
                'd65a5c9e3927c6cad47ff4fdea79904c2775afb9111d0b6dcb30e74928eb572e')
CONFIGS = Path(__file__).with_name('v52ec_expected_configs.json')
CONFIG_SHA = '3ab67ae299b82d72c7edfeca8d86477ea15bc72aa8e9290a65fcd49364bf65bd'
Z_POWER = 1.959963984540054 + 0.8416212335729143
EXTEND_ABOVE = 0.015
RC_SHA = '439cad7189ddd6f69dcc4403798cccbfdda80b4da7d6bd28b68ad283e2f66746'
RC_HELPER = Path('/private/tmp/shengji-rc-confirm-readout.P3V4ke/read_rc_confirmation.py')
SUPPORT = Path('/private/tmp/shengji-screen-health.my4RQS')
READER = Path('/private/tmp/shengji-policy-admission-20260929/server/shengji/train')
PRIMARY = Path('/private/tmp/shengji-v38div-readout.3V7AXC/vol_re.py')
ACTIVATION_FIELDS = ('lead_anchor_applied', 'lead_anchor_source', 'diversity_skipped', 'tiebreak_applied', 'tiebreak_abandoned')
LA_SOURCES = ('heuristic',)

def check_lane(*, root, reservation, status, load):
    reservation, status = Path(reservation), Path(status)
    for path in (reservation, status, CONFIGS):
        need(path.is_file() and not path.is_symlink(), 'missing/symlinked handoff metadata')
    record, digest = load(reservation)
    expected = dict(schema='claude-reservation-v1', lane='v52ec', seeds=list(HOST_SEEDS['cloud']),
        count=CLUSTERS, pairing='candidate and control on the same seeds',
        launcher='/root/claude_v52ec_screen_cloud.sh', launcher_sha256=LAUNCHER_SHA,
        status='/root/claude_v52ec_screen.status', output_root='/root/vol-screen-claude-v52ec-r38-20261005',
        expected_identity={side: sha + '  /root/claude_v52ec_expected_' + suffix + '.json'
                           for side, suffix, sha in zip(('candidate','comparator'), ('cand','cmp'), EXPECTED_SHA)})
    need(set(record) == set(expected) | {'created_at'}, 'reservation fields drift')
    need(all(record[k] == v for k, v in expected.items()), 'reservation does not bind this lane')
    need(isinstance(record['created_at'], str) and re.fullmatch(r'\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z', record['created_at']), 'invalid reservation timestamp')
    raw = status.read_bytes()
    lines = raw.decode().splitlines()
    terminal = 'v52ec PHASE B DONE (release 38 as served x5, same seeds); LANE DONE'
    need(lines and lines[-1].endswith(' ' + terminal), 'missing exact terminal line')
    need(any('armed (pid ' in line and LAUNCHER_SHA in line for line in lines), 'missing bound armed status')
    need(not any('ABORT:' in line or 'REFUSING:' in line for line in lines), 'lane failed')
    # A status file is text, so end-of-read checks handle it separately.
    return {reservation: digest}
'''
    # Add a byte fence for the status, independent of the JSON metadata fence.
    body = replace(body, "    rc = helper(rc_path)", "    status_bytes = Path(status).read_bytes()\n    rc = helper(rc_path)")
    body = replace(body, "    return attach_five_window_summaries(result, seeds=HOST_SEEDS['cloud'], prefixes=PREFIXES)",
                   "    need(Path(status).read_bytes() == status_bytes, 'status changed during readout')\n    result['terminal_status_sha256'] = hashlib.sha256(status_bytes).hexdigest()\n    return attach_five_window_summaries(result, seeds=HOST_SEEDS['cloud'], prefixes=PREFIXES)")
    main = '''
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--reservation', type=Path, required=True)
    parser.add_argument('--status', type=Path, required=True)
    args = parser.parse_args()
    helper().claim_output(args.output)
    result = analyze(args.root, reservation=args.reservation, status=args.status)
    with args.output.open('x') as handle:
        json.dump(result, handle, sort_keys=True, allow_nan=False)
        handle.write('\\n')
    print(json.dumps({k: result[k] for k in ('schema','integrity','triage','statistical_result','extension','strength_verdict')}))

if __name__ == '__main__':
    main()
'''
    result = header + '\n\n' + defs + '\n\n' + '\n\n'.join(helpers) + '\n\n' + body + main
    compile(result, 'v52ec_reader.py', 'exec')
    return result


if __name__ == '__main__':
    print(build(), end='')
