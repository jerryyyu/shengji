#!/usr/bin/env python3
"""Admit a pinned capture or an explicitly released continuation of its partial store."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
from collections import Counter
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
    if type(spec.get('split_tail_mirrors', False)) is not bool:
        raise Refused('split_tail_mirrors must be boolean')
    for path in spec['holds'] + spec['foreign_locks']:
        if present(path):
            raise Refused(f'HOLD/foreign lock: {path}')
    out = Path(spec['output'])
    resume = spec.get('resume', False)
    if type(resume) is not bool:
        raise Refused('resume must be boolean')
    if resume:
        expected = spec.get('run_id')
        if not isinstance(expected, str) or not expected:
            raise Refused('resume requires expected run_id')
        if present(out/'manifest.json'):
            raise Refused('completed store cannot resume')
        run = out/'run.json'
        if not run.is_file() or run.stat().st_size > 1_000_000:
            raise Refused('resume requires bounded run.json')
        if json.loads(run.read_text()).get('run_id') != expected:
            raise Refused('resume run_id mismatch')
    else:
        logs = [p for p in out.parent.iterdir()
                if p.name.startswith((out.name+'.log.', out.name+'.terminal.'))]
        for path in (out, Path(str(out)+'.log'), Path(str(out)+'.terminal.json'), *logs):
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
    except PermissionError:
        return True

def command(spec):
    args = [spec['python'], '-B', str(Path(spec['source_dir'])/'server/scripts/y_trajectory.py'),
            '--fly', spec['fly_path'], '--models', spec['models_path'],
            '--seed-registry', spec['seed_registry'], '--rounds', str(spec['rounds']),
            '--seed', str(spec['seed']), '--workers', str(spec['workers']),
            '--out', spec['output'], '--cap', '256']
    if spec.get('split_tail_mirrors', False):
        args.append('--split-tail-mirrors')
    if spec.get('resume', False):
        args.append('--resume')
    return args

def attempt_paths(out):
    used = [-1]
    for path in out.parent.iterdir():
        for prefix in (out.name+'.log.', out.name+'.terminal.'):
            if path.name.startswith(prefix):
                suffix = path.name[len(prefix):].removesuffix('.json')
                if suffix.isdigit():
                    used.append(int(suffix))
    if present(Path(str(out)+'.log')) or present(Path(str(out)+'.terminal.json')):
        used.append(0)
    attempt = max(used) + 1
    return attempt, Path(f'{out}.log.{attempt}'), Path(f'{out}.terminal.{attempt}.json')

def progress(spec, pid, elapsed):
    shards = Path(spec['output']) / 'shards'
    completed = sum(1 for p in shards.glob('cluster-*.jsonl')
                    if p.with_suffix('.json').is_file()) * 2
    workers = None
    try:
        rows = subprocess.check_output(['ps', '-axo', 'ppid=,args='], text=True)
        workers = sum(1 for row in rows.splitlines()
                      if row.strip() and row.strip().split(None, 1)[0] == str(pid)
                      and 'spawn_main' in row)
    except (OSError, subprocess.CalledProcessError):
        pass
    return {'event': 'progress', 'stage': 'generation', 'completed_rounds': completed,
            'total_rounds': spec['rounds'], 'percent': 100 * completed / spec['rounds'],
            'elapsed_seconds': elapsed,
            'eta_seconds': elapsed * (spec['rounds'] - completed) / completed if completed else None,
            'worker_limit': spec['workers'], 'live_worker_processes': workers,
            'deadline_headroom_seconds': max(0, spec['max_seconds'] - elapsed)}


def seal_leg(spec, out):
    """Bind the reviewed leg to its published mirrored shards before reporting completion."""
    def metadata(path):
        if path.is_symlink() or not path.is_file():
            raise Refused(f'missing or linked metadata: {path.name}')
        raw = path.read_bytes()
        return json.loads(raw), hashlib.sha256(raw).hexdigest()

    if out.is_symlink() or (out/'shards').is_symlink():
        raise Refused('linked store or shard directory')
    manifest, manifest_sha = metadata(out/'manifest.json')
    run, run_sha = metadata(out/'run.json')
    runtime, runtime_sha = metadata(out/'runtime.json')
    config = run['config']
    seed, rounds = spec['seed'], spec['rounds']
    clusters = rounds // 2
    window = manifest['seed_window']
    if (manifest['schema'] != 'shengji-trajectory-manifest-v1'
            or run['config'] != manifest['config'] or run['identity'] != manifest['identity']
            or run['identity']['git_sha'] != spec['source_git_head']
            or config['run_id'] != run['run_id'] or run['run_id'] != manifest['run_id']
            or ('run_id' in spec and run['run_id'] != spec['run_id'])
            or config['cap'] != 256 or run['identity']['fast_engine'] is not True
            or config['policy'] != spec['seal_policy'] or config['capture_served_budget'] is not True
            or config['seed0'] != seed or config['round_mix'] != 'sampled'
            or manifest['seed0'] != seed or manifest['rounds'] != rounds
            or manifest['clusters'] != clusters or len(manifest['shards']) != clusters
            or window['name'] != run['run_id'] or window['purpose'] != 'trajectory'
            or window['conflicts'] or window['allow_seed_overlap'] is not False
            or window['span'] != [seed, seed + clusters]):
        raise Refused('leg identity or seed reservation differs')
    work = runtime['clusters']
    if (runtime['resume'] != spec.get('resume', False)
            or runtime.get('split_tail_mirrors', False) != spec.get('split_tail_mirrors', False)
            or Path(runtime['seed_window']['registry']).resolve() != Path(spec['seed_registry']).resolve()
            or runtime['workers'] != spec['workers'] or work['requested'] != clusters or work['failed']
            or sorted(work['generated'] + work['reused']) != list(range(clusters))):
        raise Refused('incomplete worker coverage')
    counts = Counter()
    total_bytes = 0
    for i, shard in enumerate(manifest['shards']):
        prefix = f'shards/cluster-{i:06d}'
        if shard['path'] != prefix + '.jsonl' or shard['sidecar'] != prefix + '.json':
            raise Refused(f'wrong shard paths at cluster {i}')
        side, digest = metadata(out/shard['sidecar'])
        if (digest != shard['sidecar_sha256'] or side['run_id'] != run['run_id']
                or shard['cluster'] != i or shard['seed'] != seed + i
                or any(side[k] != shard[k] for k in ('path', 'cluster', 'seed', 'records', 'bytes', 'sha256'))
                or side['counts']['rounds'] != 2 or side['records'] != side['counts']['records']
                or [(r['mirror'], r['seed']) for r in side['rounds']] != [(0, seed+i), (1, seed+i)]):
            raise Refused(f'invalid mirror pair at cluster {i}')
        path = out/shard['path']
        if path.is_symlink() or not path.is_file() or path.stat().st_size != shard['bytes']:
            raise Refused(f'invalid trajectory file at cluster {i}')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != shard['sha256']:
                raise Refused(f'trajectory digest differs at cluster {i}')
        total_bytes += shard['bytes']
        counts.update(side['counts'])
    if counts != Counter(manifest['counts']) or counts['rounds'] != rounds:
        raise Refused('leg totals differ from published shards')
    return dict(manifest_sha256=manifest_sha, run_sha256=run_sha, runtime_sha256=runtime_sha,
                run_id=run['run_id'], seed0=seed, rounds=rounds, trajectory_bytes=total_bytes)


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
        attempt, log_path, terminal_path = attempt_paths(out)
        with log_path.open('x') as log:
            proc = subprocess.Popen(command(spec), cwd=spec['source_dir'], stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)
        safe = False
        started = time.monotonic()
        print(json.dumps({'event': 'started', 'pid': proc.pid, 'spec_sha256': spec_sha, 'attempt': attempt}), flush=True)
        status = 'running'
        next_progress = started
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
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                break
            now = time.monotonic()
            if now >= next_progress:
                print(json.dumps(progress(spec, proc.pid, now - started)), flush=True)
                next_progress = now + 60
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
        seal_fields = {}
        if status == 'completed' and 'seal_policy' in spec:
            try:
                seal_fields['leg_seal'] = seal_leg(spec, out)
            except (Refused, OSError, ValueError, KeyError, TypeError) as exc:
                seal_fields['seal_error'] = str(exc)
                status = 'invalid-store'
            if requested or any(present(p) for p in spec['holds']):
                status = requested[0] if requested else 'held'
                seal_fields.pop('leg_seal', None)
        with terminal_path.open('x') as stream:
            json.dump({'attempt': attempt, 'resume': spec.get('resume', False), 'status': status, 'returncode': rc, 'pid': proc.pid,
                       'spec_sha256': spec_sha, 'elapsed': time.monotonic()-started,
                       'lock_retained': not safe, **seal_fields}, stream)
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
