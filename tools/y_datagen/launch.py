#!/usr/bin/env python3
"""Admit one pinned, bounded capture; never restart a partial store."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

class Refused(RuntimeError):
    pass

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _spec(path, expected):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise Refused('spec SHA256 mismatch')
    return json.loads(data)

def _release(path, launcher_sha, spec_sha):
    got = json.loads(Path(path).read_text())
    if got != {'launcher_sha256': launcher_sha, 'spec_sha256': spec_sha}:
        raise Refused('RELEASE pins mismatch')

def present(path):
    return os.path.lexists(path)

def _census():
    rows = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,comm=,args='], text=True)
    parsed = [r.split(None, 3) for r in rows.splitlines() if r.strip()]
    if any(len(r) != 4 for r in parsed):
        raise Refused('incomplete process census')
    parents = {int(r[0]): int(r[1]) for r in parsed}
    ignored = set()
    pid = os.getpid()
    while pid and pid not in ignored:
        ignored.add(pid)
        pid = parents.get(pid, 0)
    for raw_pid, _, comm, argv in parsed:
        if int(raw_pid) in ignored:
            continue
        exe = Path(comm).name.lower()
        if ('python' in exe and any(s in argv for s in ('shengji', 'trajectory', 'gen-hybrid', 'claude-'))
                or exe in ('bash', 'sh', 'zsh') and '--arm' in argv):
            raise Refused(f'competing process {raw_pid}: {argv[:180]}')

def _admit(spec):
    if socket.gethostname() != spec['host']:
        raise Refused('host mismatch')
    for k in ('rounds', 'workers', 'max_seconds'):
        if type(spec[k]) is not int or spec[k] <= 0:
            raise Refused(f'invalid {k}')
    if spec['rounds'] % 2 or spec['workers'] > (os.cpu_count() or 1):
        raise Refused('invalid work size')
    for path in spec['holds'] + spec['foreign_locks']:
        if present(path):
            raise Refused(f'HOLD/foreign lock: {path}')
    out = Path(spec['output'])
    for path in (out, Path(str(out)+'.log'), Path(str(out)+'.terminal.json')):
        if present(path):
            raise Refused(f'existing output: {path}')
    if shutil.disk_usage(out.parent).free < spec['admit_disk_gib'] * 2**30:
        raise Refused('insufficient disk at admission')
    source = spec['source_dir']
    head = subprocess.check_output(['git', '-C', source, 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', source, 'status', '--porcelain', '--untracked-files=no'], text=True)
    if head != spec['source_git_head'] or dirty:
        raise Refused('source head or tracked tree drift')
    for path, expected in spec['files'].items():
        if sha256(path) != expected:
            raise Refused(f'file drift: {path}')
    _census()

def group_alive(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False

def command(spec):
    return [spec['python'], '-B', str(Path(spec['source_dir'])/'server/scripts/y_trajectory.py'),
            '--fly', spec['fly_path'], '--models', spec['models_path'],
            '--seed-registry', spec['seed_registry'], '--rounds', str(spec['rounds']),
            '--seed', str(spec['seed']), '--workers', str(spec['workers']),
            '--out', spec['output'], '--cap', '256']

def execute(spec, spec_sha, launcher):
    own_sha = sha256(launcher)
    _release(spec['release'], own_sha, spec_sha)
    _admit(spec)
    lock = Path(spec['lock'])
    lock.mkdir()
    owner = f'{os.getpid()} y-datagen {spec_sha}\n'
    (lock/'owner').write_text(owner)
    proc = None
    safe = True
    requested = []
    def stop(signum, frame):
        requested.append(f'signal-{signum}')
    old = {s: signal.signal(s, stop) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    status = 'refused'
    try:
        _admit(spec)
        _release(spec['release'], own_sha, spec_sha)
        if sha256(launcher) != own_sha:
            raise Refused('launcher changed')
        if requested:
            raise Refused('stop requested before dispatch')
        out = Path(spec['output'])
        with Path(str(out)+'.log').open('x') as log:
            proc = subprocess.Popen(command(spec), cwd=spec['source_dir'], stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)
        safe = False
        started = time.monotonic()
        print(json.dumps({'event': 'started', 'pid': proc.pid, 'spec_sha256': spec_sha}), flush=True)
        status = 'running'
        while proc.poll() is None:
            if requested:
                status = requested[0]
            elif any(present(p) for p in spec['holds']):
                status = 'held'
            elif shutil.disk_usage(out.parent).free < spec['stop_disk_gib'] * 2**30:
                status = 'disk'
            elif time.monotonic()-started >= spec['max_seconds']:
                status = 'time-cap'
            if status != 'running':
                os.killpg(proc.pid, signal.SIGTERM)
                break
            time.sleep(1)
        until = time.monotonic()+30
        while time.monotonic() < until:
            proc.poll()
            if not group_alive(proc.pid):
                safe = True
                break
            time.sleep(.2)
        rc = proc.poll()
        if status == 'running':
            status = 'completed' if rc == 0 and (out/'manifest.json').is_file() else 'failed'
        if not safe:
            status = 'containment-unresolved'
        with Path(str(out)+'.terminal.json').open('x') as stream:
            json.dump({'status': status, 'returncode': rc, 'pid': proc.pid,
                       'spec_sha256': spec_sha, 'elapsed': time.monotonic()-started,
                       'lock_retained': not safe}, stream)
        print(status, flush=True)
        return 0 if status == 'completed' else 1
    finally:
        for s, handler in old.items():
            signal.signal(s, handler)
        if safe and (lock/'owner').read_text() == owner:
            (lock/'owner').unlink()
            lock.rmdir()

def main(argv=None):
    p = argparse.ArgumentParser(allow_abbrev=False)
    p.add_argument('--spec', required=True, type=Path)
    p.add_argument('--spec-sha256', required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true')
    group.add_argument('--run', action='store_true')
    args = p.parse_args(argv)
    spec = _spec(args.spec, args.spec_sha256)
    if args.check:
        _admit(spec)
        if present(spec['lock']):
            raise Refused('host lock exists')
        print('ADMISSION CHECK PASS; RELEASE not consumed')
        return 0
    return execute(spec, args.spec_sha256, Path(__file__).resolve())

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (Refused, OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f'REFUSED: {exc}', file=sys.stderr)
        raise SystemExit(2)
