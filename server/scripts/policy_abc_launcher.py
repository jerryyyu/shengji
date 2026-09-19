"""One-shot Linux supervisor for the frozen 800-deal DEV A/B/C experiment.

Default is read-only preflight. --run requires an independently approved host
handoff; this script never stops predecessors, waits for hosts, or retries arms.
Run in an isolated source checkout, after JS9 has sealed and released its lane.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

SOURCE = 'cfcb208e238a411cf34e5a53434d3ff7799bda50'
CHECKPOINT = '8ecd4feaec480f1e76c1cc0119aed8996472512fa48eaa868415ff3d2318dd01'
SEED = 625100000
DEALS = 800
WORKERS = 12
ARM_SECONDS = 1800
LOCKS = (Path('/root/.claude-lane.lock'), Path('/root/.claude-screen.lock'))
ARMS = [('A', 4, 'policy', 'mc-smart4'),
        ('B', 16, 'policy', 'mc-smart4'),
        ('C', 4, 'policy-value', 'policy-world')]
BUSY = ('shengji.harvest.trajectory', 'cwv_screen_queue', 'policy_world_duel',
        'train_cwv.py', 'policy_head_vs_heuristic')


def commands(python, checkpoint, output):
    return [(name, [str(python), '-B', '-m', 'shengji.train.policy_world_duel',
                   '--checkpoint', str(checkpoint), '--checkpoint-sha256', CHECKPOINT,
                   '--out', str(output / name), '--seed0', str(SEED),
                   '--deals', str(DEALS), '--workers', str(WORKERS),
                   '--worlds', str(worlds), '--mode', mode, '--candidates', '8',
                   '--control', control]) for name, worlds, mode, control in ARMS]


def busy_processes():
    found = []
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit() or int(directory.name) == os.getpid():
            continue
        try:
            cmd = (directory / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
        except FileNotFoundError:
            continue
        if any(marker in cmd for marker in BUSY):
            found.append((int(directory.name), cmd[:300]))
    return found


def resource_guard(output_parent):
    available = next(int(line.split()[1]) * 1024
                     for line in Path('/proc/meminfo').read_text().splitlines()
                     if line.startswith('MemAvailable:'))
    if available < 16 * 1024**3:
        raise RuntimeError('requires at least 16 GiB available memory')
    if len(os.sched_getaffinity(0)) < WORKERS:
        raise RuntimeError('requires at least 12 available CPU cores')
    if shutil.disk_usage(output_parent).free < 5 * 1024**3:
        raise RuntimeError('requires at least 5 GiB free disk')
    busy = busy_processes()
    if busy:
        raise RuntimeError(f'host still occupied (including stopped jobs): {busy}')


def validate_summary(path):
    summary = json.loads(path.read_text())
    if (summary.get('expected') != DEALS or summary.get('complete') != DEALS
            or summary.get('errors') != []):
        raise RuntimeError('arm did not seal all 800 clean pairs')


def stop_owned_group(process):
    # Only the process group we just created, never a predecessor or peer job.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    time.sleep(2)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def interrupted(signum, _frame):
    raise SystemExit(128 + signum)


def run_arm(cmd, *, env, cwd, log, seconds=ARM_SECONDS):
    with log.open('x') as handle:
        process = subprocess.Popen(cmd, env=env, cwd=cwd, stdout=handle,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            rc = process.wait(timeout=seconds)
        except BaseException:
            stop_owned_group(process)
            raise
        if rc:
            stop_owned_group(process)
            raise RuntimeError(f'arm exited {rc}; preserve outputs, no retry')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    if sys.platform != 'linux':
        raise RuntimeError('Linux supervisor required')
    source, checkpoint, output = (p.resolve() for p in (args.source, args.checkpoint, args.out))
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True)
    if head != SOURCE or dirty:
        raise RuntimeError('source must be clean frozen cfcb208e checkout')
    if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != CHECKPOINT:
        raise RuntimeError('checkpoint mismatch')
    if output.exists() or not output.parent.is_dir():
        raise RuntimeError('fresh output under existing parent required; never resume/overwrite')
    locks = LOCKS
    if any(path.exists() for path in locks):
        raise RuntimeError('peer lane/screen reservation held')
    resource_guard(output.parent)
    env = {k: v for k, v in os.environ.items()
           if k in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR')}
    env.update(PYTHONPATH=str(source / 'server'), PYTHONDONTWRITEBYTECODE='1',
               OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
               VECLIB_MAXIMUM_THREADS='1', SHENGJI_REQUIRE_VOIDS='1')
    # Pure engine deliberately pinned; do not borrow a compiled extension from
    # a different tree. Performance/strength readouts must retain this setting.
    plan = commands(args.python.resolve(), checkpoint, output)
    print(json.dumps({'source': SOURCE, 'checkpoint': CHECKPOINT, 'commands': plan,
                      'engine': 'pure', 'arm_timeout_seconds': ARM_SECONDS}, indent=2))
    if not args.run:
        return 0
    previous = signal.signal(signal.SIGTERM, interrupted)
    acquired = []
    try:
        for path in locks:
            path.mkdir()
            acquired.append(path)
            (path / 'pid').write_text(str(os.getpid()) + '\n')
        resource_guard(output.parent)
        output.mkdir()
        for name, cmd in plan:
            resource_guard(output.parent)
            run_arm(cmd, env=env, cwd=source / 'server', log=output / f'{name}.log')
            validate_summary(output / name / 'summary.json')
        return 0
    finally:
        for path in reversed(acquired):
            # No recursive deletion; a changed lock must be inspected manually.
            if (path / 'pid').read_text().strip() == str(os.getpid()):
                (path / 'pid').unlink()
                path.rmdir()
        signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__':
    raise SystemExit(main())
