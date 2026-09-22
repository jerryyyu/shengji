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
# Bounded W256 runtime delta based on REFERENCE_SOURCE; the frozen 75bc runner
# itself accepts worlds only through 128.
PRODUCTION_WORLD_SCALING_SOURCE = '8e814f777b979b4854c2e5bfa3bfb3f792276278'
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
MC_PV_SOURCE = 'ad10d7f4c53bf8fb761e14eeede9428162f9ed32'
MC_PV_SEED = 625690000
MC_PV_ARMS = [('JS_M1_MC_PV_W1_K8', 1, 'mc-policy-value-rollout', 'mc-lcb'),
              ('JS_G1_MC_PV_W1_K8', 1, 'mc-policy-value-rollout', 'mc-lcb')]
JOINT_PRODUCTION_SUITE = 'joint-production-qualify'
JOINT_PRODUCTION_SCREEN = 'joint-production-screen'
JOINT_PRODUCTION_SEED = 626290000
JOINT_PRODUCTION_ARMS = [('JS_M1_W64_K8', 64, 'policy-value', 'production-play'),
                         ('JS_G1_W64_K8', 64, 'policy-value', 'production-play')]
PRODUCTION_WORLD_SCALING_SUITE = 'production-world-scaling-qualify'
WIDE_SCREEN = 'production-world-scaling-screen'
# PR589 review5768432397 clears source/seeds/Cloud; Jerry authorized world
# scaling and Cloud/Perf use in the operator thread. No recipe changes.
WIDE_SCREEN_HOLD = False
WIDE_SCREEN_SEED = 626600000
# Qualification94/114/146s for12pairs => ~1.7/2.1/2.7h per800.
# Six hours/arm provides tail headroom; not an ETA or retry authority.
WIDE_SCREEN_SECONDS = 21600
PRODUCTION_WORLD_SCALING_SEED = 626590000
PRODUCTION_WORLD_SCALING_ARMS = [('SOFT_W64_K8', 64, 'policy-value', 'production-play'),
                                 ('SOFT_W128_K8', 128, 'policy-value', 'production-play'),
                                 ('SOFT_W256_K8', 256, 'policy-value', 'production-play')]
JOINT_SUITES = ('joint-grid-screen', 'mc-pv-qualify', JOINT_PRODUCTION_SUITE, JOINT_PRODUCTION_SCREEN)
PRODUCTION_SUITES = ('search-reference', 'pv-production-qualify', 'pv-production-screen',
                     JOINT_PRODUCTION_SUITE, JOINT_PRODUCTION_SCREEN,
                     PRODUCTION_WORLD_SCALING_SUITE, WIDE_SCREEN)
QUALIFICATION_ONLY_SUITES = ('search-followup', 'search-reference', 'mc-pv-qualify',
                             'pv-production-qualify', JOINT_PRODUCTION_SUITE,
                             PRODUCTION_WORLD_SCALING_SUITE)
# Proposal and peer seed reservation: #436 comments5751361312/5751492758.
# Qualification only: the 800-pair screen needs a separately reviewed runtime ceiling.
PV_PRODUCTION_QUALIFY_SEED = 625790000
PV_PRODUCTION_QUALIFY_SECONDS = 3600
# Cloud qualification: 12 pairs/110.26s => ~2.04h linear for800.
# Six hours allows tails; a failure ceiling, not an ETA or retry permission.
PV_PRODUCTION_SCREEN_SECONDS = 21600
PV_PRODUCTION_SCREEN_SEED = 625800000
DEPTH_SUITE = 'depth-production-qualify'
DEPTH_SOURCE = '594404e309c8d82bdc0405f0c089126c415dd178'
DEPTH_PRODUCTION_SHA256 = 'ccade130f34ae61def540441ef997e8d41cef9df96f9683406bbba59ae4ccc75'
DEPTH_HOLD = False  # #599/#601 PASS; Jerry's cloud multi-ply request, reserved seeds
DEPTH_SEED = 626700000
DEPTH_SCREEN = 'depth-production-screen'
DEPTH_SCREEN_SOURCE = '06999b0d958abe448bd29a803c7a1f3952051743'
DEPTH_SCREEN_HOLD = False  # Jerry approved; Claude PASS #599/#601 and cloud handoff.
DEPTH_SCREEN_SEED = 626710000  # Reserved: #436 comment5771579396.
DEPTH_SCREEN_DEALS = 260
DEPTH_SCREEN_SECONDS = (1800, 1800, 18000)  # New screen ceilings, not qualification changes.
DEPTH_ARMS = [('CURRENT_TRICK', 64, 'policy-value', 'production-pv-r29'),
              ('EXTRA_TRICK_HEURISTIC', 64, 'policy-heuristic-lookahead', 'production-pv-r29'),
              ('EXTRA_TRICK_POLICY', 64, 'policy-lookahead', 'production-pv-r29')]
PRODUCTION_SUITES += (DEPTH_SUITE, DEPTH_SCREEN)
QUALIFICATION_ONLY_SUITES += (DEPTH_SUITE,)
SUITES = (DEPTH_SUITE, DEPTH_SCREEN, 'abc', 'search-followup', 'search-reference', 'strength-screen', 'wk-screen',
          'joint-grid-screen', 'mc-pv-qualify', 'pv-production-qualify', 'pv-production-screen',
          JOINT_PRODUCTION_SUITE, JOINT_PRODUCTION_SCREEN, PRODUCTION_WORLD_SCALING_SUITE,
          WIDE_SCREEN)
BUSY = ('shengji.harvest.trajectory', 'cwv_screen_queue', 'policy_world_duel',
        'train_cwv.py', 'policy_head_vs_heuristic')


def commands(python, checkpoint, output, *, qualify=False, suite='abc', production=None,
             grid_checkpoint=None, production_worlds=16):
    if suite == DEPTH_SCREEN:
        if qualify:
            raise ValueError('depth screen is full-screen only')
        plan = commands(python, checkpoint, output, qualify=True, suite=DEPTH_SUITE,
                        production=production, grid_checkpoint=grid_checkpoint,
                        production_worlds=production_worlds)
        for _, cmd in plan:
            cmd[cmd.index('--seed0') + 1] = str(DEPTH_SCREEN_SEED)
            cmd[cmd.index('--deals') + 1] = str(DEPTH_SCREEN_DEALS)
        return plan
    if suite == WIDE_SCREEN:
        if qualify:
            raise ValueError('wide-world screen is full-screen only')
        # Reuse the qualified command exactly, changing only fresh seed/count.
        plan = commands(python, checkpoint, output, qualify=True,
                        suite=PRODUCTION_WORLD_SCALING_SUITE, production=production,
                        grid_checkpoint=grid_checkpoint, production_worlds=production_worlds)
        for _, cmd in plan:
            cmd[cmd.index('--seed0') + 1] = str(WIDE_SCREEN_SEED)
            cmd[cmd.index('--deals') + 1] = str(DEALS)
        return plan
    if suite == PRODUCTION_WORLD_SCALING_SUITE and production_worlds != 16:
        raise ValueError('production-world-scaling-qualify has fixed W64/W128/W256 arms')
    if suite != PRODUCTION_WORLD_SCALING_SUITE and production_worlds not in (16, 64):
        raise ValueError('production worlds must be 16 or 64')
    if production_worlds == 64 and suite not in ('pv-production-qualify', 'pv-production-screen', JOINT_PRODUCTION_SUITE, JOINT_PRODUCTION_SCREEN):
        raise ValueError('W64 production comparison is limited to production qualification or screen')
    if suite not in SUITES:
        raise ValueError('unknown experiment suite')
    if suite == JOINT_PRODUCTION_SUITE and production_worlds != 64:
        raise ValueError('joint-production-qualify requires explicit --production-worlds 64')
    if suite == 'strength-screen' and qualify:
        raise ValueError('strength-screen is a full-screen proposal, not qualification')
    if suite in ('pv-production-screen', JOINT_PRODUCTION_SCREEN) and qualify:
        raise ValueError('pv-production-screen is full-screen only')
    if suite in ('pv-production-screen', JOINT_PRODUCTION_SCREEN) and production_worlds != 64:
        raise ValueError('pv-production-screen requires explicit --production-worlds 64')
    if suite in QUALIFICATION_ONLY_SUITES and not qualify:
        raise ValueError('search suites are qualification-only pending runtime review')
    if (suite in PRODUCTION_SUITES) != (production is not None):
        raise ValueError('production checkpoint required exactly for production suites')
    if (suite in JOINT_SUITES) != (grid_checkpoint is not None):
        raise ValueError('grid checkpoint required exactly for joint-model suites')
    arms, seed = {'abc': (ARMS, SEED), 'search-followup': (FOLLOWUP_ARMS, FOLLOWUP_SEED),
                  DEPTH_SUITE: (DEPTH_ARMS, DEPTH_SEED),
                  JOINT_PRODUCTION_SUITE: (JOINT_PRODUCTION_ARMS, JOINT_PRODUCTION_SEED),
                  JOINT_PRODUCTION_SCREEN: (JOINT_PRODUCTION_ARMS, PV_PRODUCTION_SCREEN_SEED),
                  'search-reference': (REFERENCE_ARMS, REFERENCE_SEED),
                  'strength-screen': (STRENGTH_ARMS, STRENGTH_SEED),
                  'wk-screen': (WK_ARMS, WK_QUALIFY_SEED if qualify else WK_SEED),
                  'mc-pv-qualify': (MC_PV_ARMS, MC_PV_SEED),
                  'pv-production-qualify': ([(f'SOFT_W{production_worlds}_K8', production_worlds, 'policy-value',
                                             'production-play')], PV_PRODUCTION_QUALIFY_SEED),
                  PRODUCTION_WORLD_SCALING_SUITE: (PRODUCTION_WORLD_SCALING_ARMS,
                                                   PRODUCTION_WORLD_SCALING_SEED),
                  'pv-production-screen': ([('SOFT_W64_K8', 64, 'policy-value',
                                            'production-play')], PV_PRODUCTION_SCREEN_SEED),
                  'joint-grid-screen': (JOINT_GRID_ARMS,
                                        JOINT_GRID_QUALIFY_SEED if qualify else JOINT_GRID_SEED)}[suite]
    if suite in JOINT_SUITES:
        checkpoint_specs = ((checkpoint, JS_M1_CHECKPOINT_SHA256),
                            (grid_checkpoint, GRID_CHECKPOINT_SHA256))
    else:
        checkpoint_specs = ((checkpoint, CHECKPOINT),) * len(arms)
    plan = []
    for (name, worlds, mode, control), (arm_checkpoint, arm_hash) in zip(arms, checkpoint_specs):
        plan.append((name, [str(python), '-B', '-m', 'shengji.train.policy_world_duel',
                            '--checkpoint', str(arm_checkpoint), '--checkpoint-sha256', arm_hash,
                            '--out', str(output / name), '--seed0', str(seed),
                            '--deals', str(1 if suite == 'mc-pv-qualify' else QUALIFY_DEALS if qualify else DEALS),
                            '--workers', str(6 if suite == DEPTH_SUITE else 1 if suite == 'mc-pv-qualify' else WORKERS),
                            '--worlds', str(worlds), '--mode', mode, '--candidates',
                            '16' if suite == 'wk-screen' and name == 'W4_K16' else '8',
                            '--control', control] + (['--production-checkpoint', str(production)]
                                if control in ('production-play', 'production-pv-r29') else [])))
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
            or summary.get('errors') != [] or summary.get('aggregation_error') is not None):
        raise RuntimeError(f'arm did not seal all {expected} clean pairs')


def verify_depth_import(python, source, env):
    probe = ('import json, shengji.train.policy_world_duel as d; '
             'import shengji.train.policy_lookahead as l; '
             'print(json.dumps([d.__file__, l.__file__]))')
    paths = json.loads(subprocess.check_output(
        [str(python), '-B', '-c', probe], cwd=source / 'server', env=env,
        text=True, timeout=30))
    expected = [source / 'server/shengji/train' / name
                for name in ('policy_world_duel.py', 'policy_lookahead.py')]
    if [Path(p).resolve() for p in paths] != [p.resolve() for p in expected]:
        raise RuntimeError('depth runtime imported outside frozen source')


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


def depth_screen_readout(python, source, output, recipes, env):
    """Use the pinned runtime's reader, never the supervisor checkout's imports."""
    probe = ('import json,sys,pathlib; '
             'import shengji.train.policy_depth_readout as r; '
             'assert pathlib.Path(r.__file__).resolve() == '
             'pathlib.Path(sys.argv[1]).resolve(); '
             'print(json.dumps(r.readout(sys.argv[2], json.load(sys.stdin))))')
    result = json.loads(subprocess.check_output(
        [str(python), '-B', '-c', probe,
         str(source / 'server/shengji/train/policy_depth_readout.py'), str(output)],
        input=json.dumps(recipes), env=env, cwd=source / 'server', text=True, timeout=120))
    (output / 'readout.json').write_text(json.dumps(result, indent=2) + '\n')
    if not result.get('family_complete'):
        raise RuntimeError('depth readout incomplete or unclean; preserve diagnostic')
    return result


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
                        help='JS-G1 checkpoint; required for joint-model suites')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--qualification', type=Path,
                        help='sealed wide-world qualification root; required only for its full screen')
    parser.add_argument('--depth-recipes', type=Path,
                        help='independently reviewed frozen recipe map; depth screen only')
    parser.add_argument('--suite', choices=SUITES, default='abc')
    parser.add_argument('--production-checkpoint', type=Path)
    parser.add_argument('--production-worlds', type=int, choices=(16, 64), default=16,
                        help='Single-arm budget; full screen requires64; omit for fixed world-scaling suite')
    parser.add_argument('--qualify', action='store_true',
                        help='12 pairs/900s per arm; MC uses 1 pair/3600s, PV production 12/3600s; no promotion')
    args = parser.parse_args(argv)
    if args.suite == DEPTH_SCREEN and args.run and DEPTH_SCREEN_HOLD:
        raise RuntimeError('depth screen held pending budget approval, seeds and review')
    if (args.suite == DEPTH_SCREEN) != (args.depth_recipes is not None):
        raise ValueError('frozen depth recipes required exactly for depth screen')
    if args.suite == DEPTH_SCREEN and args.qualify:
        raise ValueError('depth screen is full-screen only')
    if args.suite == DEPTH_SUITE and args.run and DEPTH_HOLD:
        raise RuntimeError('depth qualification held pending review and seed/host reconciliation')
    if (args.suite == WIDE_SCREEN) != (args.qualification is not None):
        raise ValueError('qualification root required exactly for wide-world full screen')
    if args.suite == WIDE_SCREEN:
        if args.qualify or args.production_worlds != 16:
            raise ValueError('wide-world screen is full-screen only with fixed worlds')
        if args.run and WIDE_SCREEN_HOLD:
            raise RuntimeError('wide-world launch held pending review and seed/host reconciliation')
    production_worlds = args.production_worlds
    if args.suite == PRODUCTION_WORLD_SCALING_SUITE and production_worlds != 16:
        raise ValueError('production-world-scaling-qualify has fixed W64/W128/W256 arms')
    if args.suite != PRODUCTION_WORLD_SCALING_SUITE and production_worlds not in (16, 64):
        raise ValueError('production worlds must be 16 or 64')
    if production_worlds == 64 and args.suite not in ('pv-production-qualify', 'pv-production-screen', JOINT_PRODUCTION_SUITE, JOINT_PRODUCTION_SCREEN):
        raise ValueError('W64 production comparison is limited to production qualification or screen')
    if args.suite == JOINT_PRODUCTION_SUITE and production_worlds != 64:
        raise ValueError('joint-production-qualify requires explicit --production-worlds 64')
    if args.suite in ('pv-production-screen', JOINT_PRODUCTION_SCREEN) and args.qualify:
        raise ValueError('pv-production-screen is full-screen only')
    if args.suite in ('pv-production-screen', JOINT_PRODUCTION_SCREEN) and production_worlds != 64:
        raise ValueError('pv-production-screen requires explicit --production-worlds 64')
    if args.suite == 'strength-screen':
        if args.qualify:
            raise ValueError('strength-screen is a full-screen proposal, not qualification')
    if args.suite in QUALIFICATION_ONLY_SUITES and not args.qualify:
        raise ValueError('search suites are qualification-only pending runtime review')
    if (args.suite in PRODUCTION_SUITES) != (args.production_checkpoint is not None):
        raise ValueError('production checkpoint required exactly for production suites')
    if (args.suite in JOINT_SUITES) != (args.grid_checkpoint is not None):
        raise ValueError('grid checkpoint required exactly for joint-model suites')
    source_sha = {'abc': SOURCE, 'search-followup': FOLLOWUP_SOURCE,
                  DEPTH_SUITE: DEPTH_SOURCE,
                  DEPTH_SCREEN: DEPTH_SCREEN_SOURCE,
                  JOINT_PRODUCTION_SUITE: REFERENCE_SOURCE,
                  JOINT_PRODUCTION_SCREEN: REFERENCE_SOURCE,
                  'search-reference': REFERENCE_SOURCE,
                  'strength-screen': REFERENCE_SOURCE,
                  'wk-screen': REFERENCE_SOURCE,
                  'joint-grid-screen': REFERENCE_SOURCE,
                  'pv-production-qualify': REFERENCE_SOURCE,
                  'pv-production-screen': REFERENCE_SOURCE,
                  'mc-pv-qualify': MC_PV_SOURCE,
                  PRODUCTION_WORLD_SCALING_SUITE: PRODUCTION_WORLD_SCALING_SOURCE,
                  WIDE_SCREEN: PRODUCTION_WORLD_SCALING_SOURCE}[args.suite]
    if sys.platform != 'linux':
        raise RuntimeError('Linux supervisor required')
    source, checkpoint, output = (p.resolve() for p in (args.source, args.checkpoint, args.out))
    grid_checkpoint = args.grid_checkpoint.resolve() if args.grid_checkpoint else None
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True)
    if head != source_sha or dirty:
        raise RuntimeError(f'source must be clean frozen {source_sha} checkout')
    checkpoint_sha256 = (JS_M1_CHECKPOINT_SHA256
                         if args.suite in JOINT_SUITES else CHECKPOINT)
    if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != checkpoint_sha256:
        raise RuntimeError('checkpoint mismatch')
    if (grid_checkpoint is not None
            and hashlib.sha256(grid_checkpoint.read_bytes()).hexdigest() != GRID_CHECKPOINT_SHA256):
        raise RuntimeError('grid checkpoint mismatch')
    production = args.production_checkpoint.resolve() if args.production_checkpoint else None
    production_sha = DEPTH_PRODUCTION_SHA256 if args.suite in (DEPTH_SUITE, DEPTH_SCREEN) else PRODUCTION_SHA256
    if production is not None and hashlib.sha256(production.read_bytes()).hexdigest() != production_sha:
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
                    grid_checkpoint=grid_checkpoint, production_worlds=production_worlds)
    if args.suite in (DEPTH_SUITE, DEPTH_SCREEN):
        verify_depth_import(args.python.absolute(), source, env)
    frozen_depth_recipes = None
    if args.suite == DEPTH_SCREEN:
        frozen_depth_recipes = json.loads(args.depth_recipes.read_text())
        if set(frozen_depth_recipes) != {name for name, _ in plan}:
            raise ValueError('depth frozen recipe map must name all three arms')
        for name, cmd in plan:
            recipe = frozen_depth_recipes[name]
            if (recipe.get('source_git_sha') != source_sha
                    or recipe.get('checkpoint_sha256') != CHECKPOINT
                    or recipe.get('seed0') != DEPTH_SCREEN_SEED
                    or recipe.get('deals') != DEPTH_SCREEN_DEALS
                    or recipe.get('worlds') != 64 or recipe.get('workers') != 6
                    or recipe.get('control') != 'production-pv-r29'
                    or recipe.get('decision_timeout_seconds') != 300
                    or recipe.get('policy', {}).get('mode') != cmd[cmd.index('--mode')+1]
                    or recipe.get('policy', {}).get('candidates') != 8
                    or recipe.get('control_effective', {}).get('checkpoint_sha256') != production_sha):
                raise ValueError(f'{name}: frozen depth recipe disagrees with screen command')
    if args.suite == WIDE_SCREEN:
        from shengji.train.policy_wide_world_readout import validate_qualification
        validate_qualification(args.qualification)
    seconds = (STRENGTH_ARM_SECONDS if args.suite in ('strength-screen', 'wk-screen',
                                                       'joint-grid-screen') and not args.qualify
               else QUALIFY_SECONDS if args.qualify else ARM_SECONDS)
    expected = QUALIFY_DEALS if args.qualify else DEALS
    if args.suite == DEPTH_SCREEN:
        expected = DEPTH_SCREEN_DEALS
    if args.suite == 'mc-pv-qualify':
        seconds, expected = 3600, 1
    if args.suite in ('pv-production-qualify', JOINT_PRODUCTION_SUITE,
                      PRODUCTION_WORLD_SCALING_SUITE, DEPTH_SUITE):
        seconds = PV_PRODUCTION_QUALIFY_SECONDS
    if args.suite in ('pv-production-screen', JOINT_PRODUCTION_SCREEN):
        seconds = PV_PRODUCTION_SCREEN_SECONDS
    if args.suite == WIDE_SCREEN:
        seconds = WIDE_SCREEN_SECONDS
    receipt = {'source': source_sha, 'checkpoint': CHECKPOINT, 'commands': plan,
               'suite': args.suite,
               'engine': 'pure', 'arm_timeout_seconds': seconds,
               'mode': 'runtime-qualification' if args.qualify else 'experiment',
               'automatic_promotion': False}
    if args.suite == DEPTH_SCREEN:
        receipt.update(launch_hold=DEPTH_SCREEN_HOLD, authorization='Jerry approved multi-ply screen 2026-09-22; #599',
            seed_reservation='RESERVED 626710000:626710260; #436 comment5771579396',
            expected_pairs_per_arm=DEPTH_SCREEN_DEALS, workers=6,
            arm_timeout_seconds=dict(zip((n for n, _ in plan), DEPTH_SCREEN_SECONDS)),
            total_arm_timeout_seconds=sum(DEPTH_SCREEN_SECONDS),
            control_budget_seconds=3.0, treatment_budget_seconds=300,
            automatic_retry=False, frozen_depth_recipes=frozen_depth_recipes,
            analysis={'reader': 'shengji.train.policy_depth_readout',
                      'primary_intervals': 'two depth-vs-production contrasts, Bonferroni97.5%',
                      'component_contrasts': 'exploratory matched common-opponent95%, not direct duels',
                      'qualification_rows_excluded': True, 'optional_extension': False})
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
        receipt['production_checkpoint_sha256'] = production_sha
        receipt['comparison_scope'] = 'card play only; shared heuristic declare/bury, not Fly latency'
    if args.suite == DEPTH_SUITE:
        receipt.update(launch_hold=DEPTH_HOLD, expected_pairs_per_arm=12,
                       control='production-pv-r29', control_budget_seconds=3.0,
                       treatment_budget_seconds=300,
                       workers=6, move_timeout_seconds=300,
                       seed_reservation='626700000:626700012; confirmed on PR590 and PR599',
                       authorization='Jerry direct Codex-thread request for cloud multi-ply tests',
                       runtime_review='PR601 comment5771383781 at594404e3',
                       launcher_review='PR599 comment5771387563 at3374323e; hold-only release',
                       total_arm_timeout_seconds=3*seconds,
                       automatic_retry=False, strength_claim=False)
    if args.suite == WIDE_SCREEN:
        receipt.update(mode='strength-screen', launch_hold=WIDE_SCREEN_HOLD,
            qualification=str(args.qualification.resolve()),
            seed_reservation='626600000:626600800; proposed #577, reconcile before release',
            expected_pairs_per_arm=DEALS, workers=WORKERS,
            total_arm_timeout_seconds=len(plan)*seconds, move_timeout_seconds=300,
            analysis={'primaries': ['W128 minus W64', 'W256 minus W64'],
                'interval': 'Bonferroni97.5%; matched common-opponent, not direct duels',
                'reader': 'shengji.train.policy_wide_world_readout',
                'bootstrap_seed': 20260921, 'bootstrap_replicates': 10000,
                'qualification_rows_excluded': True, 'optional_extension': False,
                'automatic_retry': False, 'automatic_promotion': False})
    if args.suite == 'pv-production-qualify':
        receipt.update(
            production_worlds=production_worlds,
            seed_reservation='625790000:625790012; #436 comment5751492758',
            expected_pairs_per_arm=QUALIFY_DEALS, workers=WORKERS,
            total_arm_timeout_seconds=seconds, move_timeout_seconds=300,
            analysis={'purpose': 'runtime/failure qualification, not strength inference',
                      'qualification_rows_excluded': True, 'automatic_retry': False,
                      'automatic_promotion': False,
                      'full_screen': 'not implemented; runtime ceiling requires qualification evidence'})
    if args.suite == PRODUCTION_WORLD_SCALING_SUITE:
        receipt.update(
            production_worlds=[64, 128, 256],
            seed_reservation='626590000:626590012; peer confirmed #436 comment5760888715',
            authorization='User direct authorization to use idle Perf for #577',
            expected_pairs_per_arm=QUALIFY_DEALS, workers=WORKERS,
            total_arm_timeout_seconds=len(plan) * seconds, move_timeout_seconds=300,
            analysis={'purpose': 'runtime/failure qualification, not strength inference',
                      'runtime_source_base': REFERENCE_SOURCE,
                      'world_diversity': 'per-decision distinct sampled deals; duplicates keep their weight; not ESS',
                      'qualification_rows_excluded': True,
                      'future_full_strength_screens': 'qualification rows excluded',
                      'automatic_retry': False, 'automatic_promotion': False,
                      'full_screen': 'not implemented; qualification only',
                      'readout': 'unavailable pending qualification and separately reviewed W256 reader'})
    if args.suite == 'pv-production-screen':
        receipt.update(
            mode='strength-screen',
            production_worlds=production_worlds,
            seed_reservation='625800000:625800800; #436 comment5751492758',
            qualification_evidence='PR553 comment5754787486;12 clean pairs/110.26s',
            expected_pairs_per_arm=DEALS, workers=WORKERS,
            total_arm_timeout_seconds=seconds, move_timeout_seconds=300,
            analysis={
                'primary': 'soft W64/K8 minus production-play paired signed-level mean',
                'unit': 'deal with both seat mirrors averaged',
                'interval': 'two-sided95% paired deal bootstrap;10000 resamples',
                'bootstrap_seed': 20260920,
                'qualification_rows_excluded': True,
                'optional_extension': False, 'automatic_retry': False,
                'decision_rule': 'superiority requires lower bound above zero; null is not equivalence',
                'scope': 'direct card-play comparison, not full Fly package or latency'})
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
    if args.suite in (JOINT_PRODUCTION_SUITE, JOINT_PRODUCTION_SCREEN):
        receipt.update(
            checkpoint=JS_M1_CHECKPOINT_SHA256,
            grid_checkpoint=GRID_CHECKPOINT_SHA256,
            checkpoint_identities=dict(zip((name for name, _ in plan),
                (JS_M1_CHECKPOINT_SHA256, GRID_CHECKPOINT_SHA256))),
            seed_reservation='626290000:626290012; proposed on issue436; confirm before launch',
            production_worlds=64, expected_pairs_per_arm=QUALIFY_DEALS, workers=WORKERS,
            total_arm_timeout_seconds=len(plan) * seconds, move_timeout_seconds=300,
            analysis={'purpose': 'runtime/failure qualification, not strength inference',
                      'qualification_rows_excluded': True, 'automatic_retry': False,
                      'automatic_promotion': False,
                      'full_screen': 'not enabled; requires qualification evidence and runtime review'})
        if args.suite == JOINT_PRODUCTION_SCREEN:
            receipt.update(
                mode='strength-screen', expected_pairs_per_arm=DEALS,
                seed_reservation='625800000:625800800; matched window, #436 comment5755077257',
                qualification_evidence='PR570 comment5756493934; M1/G1 each12 clean pairs,107.47s/120.06s',
                analysis={
                    'primaries': 'M1 and G1 W64/K8 minus production-play paired signed levels',
                    'unit': 'deal with both seat mirrors averaged',
                    'interval': 'two-sided97.5% per primary, Bonferroni two comparisons;10000 resamples',
                    'bootstrap_seed': 20260921,
                    'model_contrast': 'G1 minus M1, exploratory95%, matched common-opponent not direct duel',
                    'reader': 'shengji.train.policy_joint_production_readout',
                    'qualification_rows_excluded': True, 'optional_extension': False,
                    'automatic_retry': False, 'automatic_promotion': False,
                    'decision_rule': 'superiority requires lower bound above zero; null is not equivalence'})
    if args.suite == 'mc-pv-qualify':
        receipt.update(
            checkpoint=JS_M1_CHECKPOINT_SHA256,
            grid_checkpoint=GRID_CHECKPOINT_SHA256,
            checkpoint_identities=dict(zip((name for name, _ in plan),
                (JS_M1_CHECKPOINT_SHA256, GRID_CHECKPOINT_SHA256))),
            seed_reservation='625690000:625690001; DEV qualification only',
            comparison_scope='card play only; shared heuristic declare/bury',
            expected_pairs_per_arm=1, workers=1,
            total_arm_timeout_seconds=len(plan) * seconds,
            move_timeout_seconds=300,
            analysis={'purpose': 'full-game runtime and failure qualification, not strength inference',
                      'qualification_rows_excluded': True,
                      'automatic_retry': False, 'automatic_promotion': False})
    print(json.dumps(receipt, indent=2))
    if not args.run:
        return 0
    previous = signal.signal(signal.SIGTERM, interrupted)
    acquired = []
    created_output = False
    completed_arms = []
    try:
        for path in locks:
            path.mkdir()
            acquired.append(path)
            (path / 'pid').write_text(str(os.getpid()) + '\n')
        resource_guard(output.parent)
        output.mkdir()
        created_output = True
        (output / 'launch-plan.json').write_text(json.dumps(receipt, indent=2) + '\n')
        for arm_index, (name, cmd) in enumerate(plan):
            resource_guard(output.parent)
            run_arm(cmd, env=env, cwd=source / 'server', log=output / f'{name}.log',
                    seconds=DEPTH_SCREEN_SECONDS[arm_index] if args.suite == DEPTH_SCREEN else seconds)
            validate_summary(output / name / 'summary.json', expected=expected)
            completed_arms.append(name)
        if args.suite == DEPTH_SCREEN:
            depth_screen_readout(args.python.absolute(), source, output, frozen_depth_recipes, env)
        if args.suite in (DEPTH_SUITE, DEPTH_SCREEN):
            (output / 'terminal.json').write_text(json.dumps(
                {'status': 'complete', 'completed_arms': completed_arms,
                 'automatic_promotion': False}) + '\n')
        if args.suite == WIDE_SCREEN:
            from shengji.train.policy_wide_world_readout import readout
            result = readout(output, args.qualification)
            (output / 'readout.json').write_text(json.dumps(result, indent=2) + '\n')
        return 0
    except BaseException as exc:
        if args.suite in (DEPTH_SUITE, DEPTH_SCREEN) and created_output:
            (output / 'terminal.json').write_text(json.dumps(
                {'status': 'refused', 'completed_arms': completed_arms,
                 'error_type': type(exc).__name__, 'error': str(exc),
                 'automatic_retry': False}) + '\n')
        raise
    finally:
        for path in reversed(acquired):
            # No recursive deletion; a changed lock must be inspected manually.
            if (path / 'pid').read_text().strip() == str(os.getpid()):
                (path / 'pid').unlink()
                path.rmdir()
        signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__':
    raise SystemExit(main())
