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
# Perf pure-engine qualification (12 pairs, 12 workers): A/B/C 17.38/17.12/10.70s.
# Linear 800-pair estimates peak at ~1159s; allow ~3.1x for startup/tail variation.
# This ceiling is a failure bound, not an ETA or automatic retry authorization.
ARM_SECONDS = 3600
QUALIFY_DEALS = 12
QUALIFY_SECONDS = 900
LOCKS = (Path('/root/.claude-lane.lock'), Path('/root/.claude-screen.lock'))
ARMS = [('A', 4, 'policy', 'mc-smart4'),
        ('B', 16, 'policy', 'mc-smart4'),
        ('C', 4, 'policy-value', 'policy-world')]
FOLLOWUP_SOURCE = '4976104af96d44f1ab7ca483ff823b849521d5de'
# Fresh DEV window; qualification rows must never be pooled into a later screen.
FOLLOWUP_SEED = 625200000
FOLLOWUP_ARMS = [('D', 4, 'policy-value', 'mc-lcb'),
                 ('E', 4, 'policy-selective-mc', 'policy-value')]
REFERENCE_SOURCE = '75bc524a1580d8fe8d306b4977f1a6346a9d1027'
PRODUCTION_SHA256 = '0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747'
JS_M1_CHECKPOINT_SHA256 = 'a5248cc5ae97e69687910e892b1905613a1735cb47cbdc5e73a76e41d61e3f38'
GRID_CHECKPOINT_SHA256 = '9ee9fedb38950aa3630cf246d3eca0608f4dce516650182522ce69e7a0960cf0'
# Descriptive alias for the second joint-screen identity.
JS_G1_CHECKPOINT_SHA256 = GRID_CHECKPOINT_SHA256
REFERENCE_SEED = 625300000
REFERENCE_ARMS = [('F', 4, 'policy-lookahead', 'policy-value'),
                  ('G', 4, 'policy-value', 'production-play')]
# Jerry directly approved this exact screen in the Codex thread on Sept 20 UTC.
# Claude confirmed the window free on #521. Never reuse qualification rows.
STRENGTH_SEED = 625400000
STRENGTH_ARMS = [('PV', 4, 'policy-value', 'mc-lcb'),
                 ('PV_MC', 4, 'policy-selective-mc', 'mc-lcb'),
                 ('PV_TREE', 4, 'policy-lookahead', 'mc-lcb')]
# D's 12-pair MC-LCB qualification took 80s (~89min/800 linear).
# Allow 3h/arm for added tree work and tails; this is not a runtime promise.
STRENGTH_ARM_SECONDS = 10800
WK_SEED = 625500000
WK_QUALIFY_SEED = 625490000
WK_ARMS = [('W4_K8', 4, 'policy-value', 'mc-lcb'),
           ('W16_K8', 16, 'policy-value', 'mc-lcb'),
           ('W4_K16', 4, 'policy-value', 'mc-lcb')]
JOINT_GRID_SEED = 625600000
JOINT_GRID_QUALIFY_SEED = 625590000
JOINT_GRID_ARMS = [('JS_M1_W4_K8', 4, 'policy-value', 'mc-lcb'),
                   ('JS_G1_W4_K8', 4, 'policy-value', 'mc-lcb')]
SUITES = ('abc', 'search-followup', 'search-reference', 'strength-screen', 'wk-screen',
          'joint-grid-screen')
BUSY = ('shengji.harvest.trajectory', 'cwv_screen_queue', 'policy_world_duel',
        'train_cwv.py', 'policy_head_vs_heuristic')


def commands(python, checkpoint, output, *, qualify=False, suite='abc', production=None,
             grid_checkpoint=None):
    if suite not in SUITES:
        raise ValueError('unknown experiment suite')
    if suite == 'strength-screen' and qualify:
        raise ValueError('strength-screen is a full-screen proposal, not qualification')
    if suite in ('search-followup', 'search-reference') and not qualify:
        raise ValueError('search suites are qualification-only pending runtime review')
    if (suite == 'search-reference') != (production is not None):
        raise ValueError('production checkpoint required exactly for search-reference')
    if (suite == 'joint-grid-screen') != (grid_checkpoint is not None):
        raise ValueError('grid checkpoint required exactly for joint-grid-screen')
    arms, seed = {'abc': (ARMS, SEED), 'search-followup': (FOLLOWUP_ARMS, FOLLOWUP_SEED),
                  'search-reference': (REFERENCE_ARMS, REFERENCE_SEED),
                  'strength-screen': (STRENGTH_ARMS, STRENGTH_SEED),
                  'wk-screen': (WK_ARMS, WK_QUALIFY_SEED if qualify else WK_SEED),
                  'joint-grid-screen': (JOINT_GRID_ARMS,
                                        JOINT_GRID_QUALIFY_SEED if qualify else JOINT_GRID_SEED)}[suite]
    if suite == 'joint-grid-screen':
        checkpoint_specs = ((checkpoint, JS_M1_CHECKPOINT_SHA256),
                            (grid_checkpoint, GRID_CHECKPOINT_SHA256))
    else:
        checkpoint_specs = ((checkpoint, CHECKPOINT),) * len(arms)
    plan = []
    for (name, worlds, mode, control), (arm_checkpoint, arm_hash) in zip(arms, checkpoint_specs):
        plan.append((name, [str(python), '-B', '-m', 'shengji.train.policy_world_duel',
                            '--checkpoint', str(arm_checkpoint), '--checkpoint-sha256', arm_hash,
                            '--out', str(output / name), '--seed0', str(seed),
                            '--deals', str(QUALIFY_DEALS if qualify else DEALS), '--workers', str(WORKERS),
                            '--worlds', str(worlds), '--mode', mode, '--candidates',
                            '16' if suite == 'wk-screen' and name == 'W4_K16' else '8',
                            '--control', control] + (['--production-checkpoint', str(production)]
                                if control == 'production-play' else [])))
    return plan


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


def validate_summary(path, *, expected=DEALS):
    summary = json.loads(path.read_text())
    if (summary.get('expected') != expected or summary.get('complete') != expected
            or summary.get('errors') != []):
        raise RuntimeError(f'arm did not seal all {expected} clean pairs')


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
    parser.add_argument('--grid-checkpoint', type=Path,
                        help='JS-G1 checkpoint; required only for joint-grid-screen')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--suite', choices=SUITES, default='abc')
    parser.add_argument('--production-checkpoint', type=Path)
    parser.add_argument('--qualify', action='store_true',
                        help='12 pairs per arm, 900s/arm ceiling; never advances to full experiment')
    args = parser.parse_args(argv)
    if args.suite == 'strength-screen':
        if args.qualify:
            raise ValueError('strength-screen is a full-screen proposal, not qualification')
    if args.suite in ('search-followup', 'search-reference') and not args.qualify:
        raise ValueError('search suites are qualification-only pending runtime review')
    if (args.suite == 'search-reference') != (args.production_checkpoint is not None):
        raise ValueError('production checkpoint required exactly for search-reference')
    if (args.suite == 'joint-grid-screen') != (args.grid_checkpoint is not None):
        raise ValueError('grid checkpoint required exactly for joint-grid-screen')
    source_sha = {'abc': SOURCE, 'search-followup': FOLLOWUP_SOURCE,
                  'search-reference': REFERENCE_SOURCE,
                  'strength-screen': REFERENCE_SOURCE,
                  'wk-screen': REFERENCE_SOURCE,
                  'joint-grid-screen': REFERENCE_SOURCE}[args.suite]
    if sys.platform != 'linux':
        raise RuntimeError('Linux supervisor required')
    source, checkpoint, output = (p.resolve() for p in (args.source, args.checkpoint, args.out))
    grid_checkpoint = args.grid_checkpoint.resolve() if args.grid_checkpoint else None
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True)
    if head != source_sha or dirty:
        raise RuntimeError(f'source must be clean frozen {source_sha} checkout')
    checkpoint_sha256 = (JS_M1_CHECKPOINT_SHA256
                         if args.suite == 'joint-grid-screen' else CHECKPOINT)
    if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != checkpoint_sha256:
        raise RuntimeError('checkpoint mismatch')
    if (grid_checkpoint is not None
            and hashlib.sha256(grid_checkpoint.read_bytes()).hexdigest() != GRID_CHECKPOINT_SHA256):
        raise RuntimeError('grid checkpoint mismatch')
    production = args.production_checkpoint.resolve() if args.production_checkpoint else None
    if production is not None and hashlib.sha256(production.read_bytes()).hexdigest() != PRODUCTION_SHA256:
        raise RuntimeError('production checkpoint mismatch')
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
    # Resolving a venv interpreter symlink selects the system Python and loses
    # the venv's dependencies. Make the path absolute without dereferencing it.
    plan = commands(args.python.absolute(), checkpoint, output,
                    qualify=args.qualify, suite=args.suite, production=production,
                    grid_checkpoint=grid_checkpoint)
    seconds = (STRENGTH_ARM_SECONDS if args.suite in ('strength-screen', 'wk-screen',
                                                       'joint-grid-screen') and not args.qualify
               else QUALIFY_SECONDS if args.qualify else ARM_SECONDS)
    expected = QUALIFY_DEALS if args.qualify else DEALS
    receipt = {'source': source_sha, 'checkpoint': CHECKPOINT, 'commands': plan,
               'suite': args.suite,
               'engine': 'pure', 'arm_timeout_seconds': seconds,
               'mode': 'runtime-qualification' if args.qualify else 'experiment',
               'automatic_promotion': False}
    if args.suite == 'strength-screen':
        receipt.update(
            mode='strength-screen', launch_hold=False,
            seed_reservation='625400000:625400800; peer confirmed on PR521',
            authorization='Jerry direct Codex-thread approval, 2026-09-20 UTC',
            comparison_scope='card play only; shared heuristic declare/bury',
            total_arm_timeout_seconds=len(plan) * seconds,
            analysis={
                'primary': 'paired signed-level advantage against MC-LCB per arm',
                'unit': 'deal with both seat mirrors averaged',
                'component_contrasts': ['PV_MC minus PV', 'PV_TREE minus PV'],
                'familywise_intervals': 'two-sided 98.333333% per primary contrast (Bonferroni, three arms)',
                'descriptive_intervals': 'two-sided 95%; component contrasts exploratory',
                'qualification_rows_excluded': True,
                'optional_extension': False,
            })
    if production is not None:
        receipt['production_checkpoint_sha256'] = PRODUCTION_SHA256
        receipt['comparison_scope'] = 'card play only; shared heuristic declare/bury, not Fly latency'
    if args.suite == 'wk-screen':
        receipt.update(
            launch_hold=False,
            authorization='Jerry direct Codex-thread approval: Yea lets test that, 2026-09-20',
            comparison_scope='card play only; shared heuristic declare/bury',
            total_arm_timeout_seconds=len(plan) * seconds,
            analysis={
                'primary': 'paired signed-level advantage against MC-LCB per arm',
                'unit': 'deal with both seat mirrors averaged',
                'component_contrasts': ['W16_K8 minus W4_K8', 'W4_K16 minus W4_K8'],
                'familywise_intervals': '98.333333% per primary contrast (Bonferroni, three arms)',
                'component_intervals': '97.5% per component contrast (Bonferroni, two contrasts)',
                'descriptive_intervals': '95%; no optional extension',
                'qualification_rows_excluded': True,
                'optional_extension': False,
            })
    if args.suite == 'joint-grid-screen':
        receipt.update(
            checkpoint=JS_M1_CHECKPOINT_SHA256,
            grid_checkpoint=GRID_CHECKPOINT_SHA256,
            checkpoint_identities={
                'JS_M1_W4_K8': JS_M1_CHECKPOINT_SHA256,
                'JS_G1_W4_K8': GRID_CHECKPOINT_SHA256,
            },
            launch_hold=False,
            authorization='Jerry direct Codex-thread approval: grid screen, 2026-09-20 UTC',
            seed_reservation=(
                'qualification 625590000:625590012; full 625600000:625600800; '
                'Claude reports no collision in bus codex:993; disjoint local W/K windows'),
            comparison_scope='card play only; shared heuristic declare/bury',
            total_arm_timeout_seconds=len(plan) * seconds,
            analysis={
                'primary': 'two paired signed-level contrasts against fixed MC-LCB',
                'primary_contrasts': [
                    'JS_M1_W4_K8 minus MC-LCB', 'JS_G1_W4_K8 minus MC-LCB'],
                'primary_intervals': 'two-sided adjusted 97.5% intervals (Bonferroni, two contrasts)',
                'matched_contrast': 'JS_G1_W4_K8 minus JS_M1_W4_K8 (matched grid-minus-MLP)',
                'matched_intervals': 'two-sided 95% interval',
                'unit': 'deal with both seat mirrors averaged',
                'qualification_rows_excluded': True,
                'optional_extension': False,
            })
    print(json.dumps(receipt, indent=2))
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
        (output / 'launch-plan.json').write_text(json.dumps(receipt, indent=2) + '\n')
        for name, cmd in plan:
            resource_guard(output.parent)
            run_arm(cmd, env=env, cwd=source / 'server', log=output / f'{name}.log',
                    seconds=seconds)
            validate_summary(output / name / 'summary.json', expected=expected)
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
