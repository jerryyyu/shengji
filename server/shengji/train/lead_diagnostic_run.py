"""Pinned saved-result diagnostic runner; authority and host admission are external.

Invoke the supervisor by file path (not ``-m``) so no shengji package import
precedes environment isolation::

    python server/shengji/train/lead_diagnostic_run.py --spec RUN.json --sha256 SHA OUTPUT.json

Only the supervisor invocation is launchable; --worker is its private child path.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


def pinned_json(path, expected, limit):
    with open(path, 'rb') as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError('input exceeds byte limit')
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('input hash mismatch')
    return json.loads(data)


@contextmanager
def termination_guard():
    signals = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
    previous = {sig: signal.getsignal(sig) for sig in signals}
    deferred = True
    pending = None

    def terminate(sig, frame):
        nonlocal pending
        # A second signal must not interrupt process-group cleanup and reaping.
        for item in signals:
            signal.signal(item, signal.SIG_IGN)
        if deferred:
            pending = sig
        else:
            raise SystemExit(128 + sig)

    def child_owned():
        nonlocal deferred
        deferred = False
        if pending is not None:
            raise SystemExit(128 + pending)

    try:
        for sig in signals:
            signal.signal(sig, terminate)
        yield child_owned
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def supervise(command, output, seconds, *, expected, env=None):
    """Bound one child process group and publish its JSON only on successful exit.

    command receives a private output path as its final argument. The final
    destination must not exist; a hard link publishes complete bytes atomically.
    """
    if not math.isfinite(seconds) or not 0 < seconds <= 300:
        raise ValueError('wall limit must be in (0, 300] seconds')
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    with tempfile.TemporaryDirectory(prefix='.lead-diagnostic-', dir=output.parent) as tmp:
        partial = Path(tmp) / 'result.json'
        with termination_guard() as child_owned:
            child = subprocess.Popen([*command, str(partial)], start_new_session=True, env=env)
            try:
                child_owned()
                rc = child.wait(timeout=seconds)
            finally:
                # Stop the process group even when native inference ignores the gate.
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
        if rc != 0:
            raise RuntimeError(f'diagnostic child exited {rc}')
        data = partial.read_bytes()
        result = json.loads(data, parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f'nonfinite result: {value}')))
        if result.get('schema') != 'saved-lead-diagnostic-v1':
            raise ValueError('unexpected result schema')
        if any(result.get(key) != value for key, value in expected.items()):
            raise ValueError('result identity mismatch')
        os.link(partial, output)


def recipe_environment(spec):
    if spec.get('schema') != 'saved-lead-run-v1':
        raise ValueError('unexpected run schema')
    env = spec['env']
    if (not isinstance(env, dict) or not env
            or any(not k.startswith('SHENGJI_') or not isinstance(v, str)
                   for k, v in env.items())):
        raise ValueError('invalid recipe environment')
    if env.get('SHENGJI_BOT') != spec['policy'] or not spec['policy'].startswith('pv-search-'):
        raise ValueError('policy mismatch')
    return {**{k: v for k, v in os.environ.items() if not k.startswith('SHENGJI_')}, **env}


def worker(spec_path, spec_sha, output):
    spec = pinned_json(spec_path, spec_sha, 65536)
    env = recipe_environment(spec)
    for key in list(os.environ):
        if key.startswith('SHENGJI_'):
            del os.environ[key]
    os.environ.update(env)
    saved = pinned_json(spec['saved_path'], spec['saved_sha256'], 32 * 1024 * 1024)
    # Import only after the pinned environment controls registry registration.
    from shengji.ai.registry import make_bot
    from .lead_saved_diagnostic import diagnose_saved_leads
    deadline = time.monotonic() + spec['wall_seconds']

    def gate():
        if time.monotonic() >= deadline:
            raise TimeoutError('diagnostic cooperative deadline')

    result = diagnose_saved_leads(saved, spec['cases'],
                                 lambda seed: make_bot(spec['policy'], seed=seed), gate=gate)
    result['run_spec_sha256'] = spec_sha
    result['saved_sha256'] = spec['saved_sha256']
    result['policy'] = spec['policy']
    with open(output, 'x') as target:
        json.dump(result, target, allow_nan=False)
        target.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('output')
    args = parser.parse_args()
    if args.worker:
        worker(args.spec, args.sha256, args.output)
        return
    spec = pinned_json(args.spec, args.sha256, 65536)
    supervise([sys.executable, '-m', 'shengji.train.lead_diagnostic_run',
               '--worker', '--spec', str(Path(args.spec).resolve()), '--sha256', args.sha256],
              args.output, spec['wall_seconds'], env=recipe_environment(spec),
              expected={'run_spec_sha256': args.sha256,
                        'saved_sha256': spec['saved_sha256'], 'policy': spec['policy']})


if __name__ == '__main__':
    main()
