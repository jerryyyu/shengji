"""Outcome-blind config capture on the pinned cloud tree; no model/round work.

Run through the cloud Python with this file on stdin. Reuses the already
frozen producer bot identities, suppresses only output-lock acquisition and
bot construction, and stops at bind_output_config before any output I/O.
"""
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path('/root/claude-main-28')
TREE = 'f7b5ed04c25a48204869f13583d6d6d3242ea305'
PINS = (
    ('cand', 'c04c5a9fecaf6e40fff73635c6e0eccdb9e76113c8af43920439128801eb0a9c'),
    ('cmp', '601a6406e662fc9878d7cd294896947508549ba34e2c7934526879200bc79fb1'),
)
assert subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip() == TREE
assert not subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain', '--', 'server'], text=True)
frozen = []
for side, sha in PINS:
    raw = Path(f'/root/claude_v53dts_expected_{side}.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sha
    frozen.append(json.loads(raw))
for key in list(os.environ):
    if key.startswith('SHENGJI_'):
        del os.environ[key]
os.environ.update(frozen[0]['environment'])
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[key] = '1'
sys.path.insert(0, str(ROOT / 'server'))
from shengji.train import cwv_shortlist_screen as scr
assert Path(scr.__file__).resolve() == ROOT / 'server/shengji/train/cwv_shortlist_screen.py'


class Captured(Exception):
    pass


configs = []
def capture(path, config):
    configs.append(copy.deepcopy(config))
    raise Captured


sentinel = object()
scr.make_bot = lambda *args, **kwargs: sentinel
scr.screen_output_lock = lambda *args: contextlib.nullcontext()
scr.bind_output_config = capture
source = scr.execution_source_identity(ROOT / 'server/shengji')
scr.execution_source_identity = lambda *args: copy.deepcopy(source)
for expected in frozen:
    for key in list(os.environ):
        if key.startswith('SHENGJI_'):
            del os.environ[key]
    os.environ.update(expected['environment'])
    def identity(bot):
        assert bot is sentinel
        return copy.deepcopy(expected['arm_policy_identity'])
    scr._policy_identity = identity
    try:
        scr.main(['--arm', 'policy', '--arm-policy', expected['arm_policy'],
                  '--baseline', 'production', '--trump-ranks', '2,3,4,5,6,7,8,9,10,J,Q,K,A',
                  '--clusters', '520', '--workers', '14', '--seed0', '53060910',
                  '--out', '/__v53dts_probe_must_never_create__', '--decision-deadline', '300'])
    except Captured:
        pass
    else:
        raise AssertionError('did not stop at config binding')
assert len(configs) == 2
print(json.dumps(configs, indent=2, sort_keys=True, allow_nan=False))

