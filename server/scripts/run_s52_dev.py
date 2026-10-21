"""Fixed S52 DEV worker; only an independently reviewed host launcher may invoke it.

This draft does not grant admission or create RELEASE. Source staging and the
external host-lock/token-drain wrapper are required before execution.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import resource
import signal
import socket
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parent
TREE = Path('/root/codex-s52dev-src-99661691')
HEAD = '996616915d5a5d39833758d77964e37466e4ef41'
HOST = 'ubuntu-32gb-hel1-2'
OUT = ROOT / 'output'
PV = Path('/root/models/smv3out-491ee4bf.npz')
BELIEF = Path('/root/models/s17long-e2-763b5e05.npz')
PINS = {PV: '491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670',
        BELIEF: '763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343'}
EXTENSIONS = {
    'shengji.engine._fast': '99472ae0396967ea02bc7fcb1d7c6bee5438a5549f7d3b405061862d3de4299a',
    'shengji.ai._endgame_fast': '52759fde0b3e0c080fce7db19180ee53ae1f1b77657143a3d2c88e8f9bef73ec',
    'shengji.ai._cwv_math': '1da16497b194f965d9b0a289c3c6b00ddc346490a33f2c4d1da288058ad50606',
}
SO_SUFFIX = '.cpython-314-x86_64-linux-gnu.so'
CANDIDATE_BOT = 'pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-lar-la-dtr-vd-vdef-ed7-xf7-xfcompactlevel-r250a42e1-bury-hybrid-bwv-ef1b87579f4c'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refuse(message):
    raise SystemExit('REFUSE: ' + message)


def verify_extensions(*, loaded=False):
    for name, sha in EXTENSIONS.items():
        path = TREE / 'server' / (name.replace('.', '/') + SO_SUFFIX)
        if path.is_symlink() or not path.is_file() or digest(path) != sha:
            refuse('compiled artifact drift: ' + name)
        if loaded:
            module = importlib.import_module(name)
            if Path(module.__file__).resolve() != path.resolve():
                refuse('compiled import origin drift: ' + name)


def arms():
    control = tomllib.loads((TREE / 'fly.toml').read_text())['env']
    control.update(SHENGJI_PV_CKPT=str(PV), SHENGJI_PV_BELIEF_CKPT=str(BELIEF))
    candidate = {**control, 'SHENGJI_PV_LEAD_ALIAS_REFILL': '1', 'SHENGJI_BOT': CANDIDATE_BOT}
    return control, candidate


def work():
    sys.path.insert(0, str(TREE / 'server'))
    verify_extensions(loaded=True)
    from scripts.pv_dev_duel import run_shards
    control, candidate = arms()
    run_shards(control, candidate, out=OUT, seed0=184060910, pairs=624,
               ranks='2,3,4,5,6,7,8,9,10,J,Q,K,A', cluster0=0,
               round_kind='fixed_banker', workers=14)


def supervised_work():
    sys.path.insert(0, str(TREE / 'server'))
    from scripts.s11_input_guard import supervise_s11_input
    command = [sys.executable, '-c', 'import run_s52_dev; run_s52_dev.work()']
    with (ROOT / 'worker.log').open('x') as log:
        result = supervise_s11_input(command, cwd=ROOT,
            env=dict(os.environ, PYTHONPATH=str(TREE / 'server')),
            log=log, python=sys.executable, wall_seconds=7200,
            rss_threshold_bytes=8 << 30, sample_seconds=0.25,
            term_grace_seconds=0.5)
    return result


def other_venv_pythons():
    census = subprocess.check_output(['ps', '-axo', 'pid=,args='], text=True)
    found = []
    for line in census.splitlines():
        pid, _, command = line.strip().partition(' ')
        command = command.strip()
        if pid != str(os.getpid()) and 'server/.venv/bin/python' in command and not command.startswith(('zsh ', 'bash ', '/bin/zsh ', '/bin/bash ')):
            found.append(pid)
    return found


def preflight():
    if socket.gethostname() != HOST:
        refuse('wrong host')
    if subprocess.check_output(['git', '-C', str(TREE), 'rev-parse', 'HEAD'], text=True).strip() != HEAD:
        refuse('source head drift')
    if subprocess.check_output(['git', '-C', str(TREE), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        refuse('tracked source dirty')
    if any(digest(path) != sha for path, sha in PINS.items()):
        refuse('package drift')
    verify_extensions()


def dry():
    preflight()
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
        os.environ[name] = '1'
    os.environ['SHENGJI_FAST'] = '1'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.path.insert(0, str(TREE / 'server'))
    verify_extensions(loaded=True)
    started = time.monotonic()
    from scripts.pv_dev_duel import register_pair
    control, candidate = arms()
    names = register_pair(control, candidate)
    print(json.dumps(dict(dry='S52DEV DRY OK', control=names[0], candidate=names[1],
                          construct_seconds=round(time.monotonic() - started, 2),
                          ru_maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                          other_venv_pythons_now=len(other_venv_pythons()),
                          output_exists=OUT.exists(), claim_exists=(ROOT / 'CLAIM').exists()), sort_keys=True))


def main():
    preflight()
    if OUT.exists() or (ROOT / 'CLAIM').exists() or (ROOT / 'worker.log').exists():
        refuse('prior output/claim/worker log; no automatic retry')
    if other_venv_pythons():
        refuse('another server-venv Python process is present')
    (ROOT / 'CLAIM').mkdir()
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
        os.environ[name] = '1'
    os.environ['SHENGJI_FAST'] = '1'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.nice(19)
    def stop(signum, frame):
        raise SystemExit(f'ABORT signal={signum}; preserve output and claim')
    for sig in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)
    started = time.monotonic()
    supervision = supervised_work()
    if supervision['exit_cause'] != 'process-exited' or supervision['returncode'] != 0:
        raise RuntimeError('DEV worker failed: ' + json.dumps(supervision, sort_keys=True))
    if (OUT / 'DONE').read_text() != '624 complete pairs in 14 shards\n':
        refuse('worker terminal does not match the fixed population')
    print(json.dumps(dict(terminal='DEV DONE', elapsed_seconds=time.monotonic()-started,
                          supervision=supervision,
                          health=[json.loads((OUT / f'shard-{i:03d}' / 'health.json').read_text())
                                  for i in range(14)]), sort_keys=True))


if __name__ == '__main__':
    if sys.argv[1:] == ['--dry']:
        dry()
    elif sys.argv[1:]:
        refuse('unexpected arguments')
    else:
        main()

