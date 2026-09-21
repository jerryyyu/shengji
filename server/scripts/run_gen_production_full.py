"""Guarded gen4/gen3 full-screen supervisor, held until qualification pins seal.

No wait, predecessor management, retry or automatic qualification promotion.
The caller must independently verify the named host's reservation/handover.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import policy_abc_launcher as supervisor
from plan_gen_production_full import packet


def qualification_gate(joint, gen4, gen3):
    # Resolve our own reviewed sibling package, never an unrelated installation.
    server = str(Path(__file__).resolve().parents[1])
    if server not in sys.path:
        sys.path.insert(0, server)
    from shengji.train.policy_four_model_readout import QUALIFICATION_HASHES
    if any(value is None for value in QUALIFICATION_HASHES.values()):
        raise RuntimeError('launch held: qualification identities not frozen')
    from shengji.train.policy_world_compare import _read
    evidence = {}
    roots = [joint, joint, gen4, gen3]
    seeds = [626290000, 626290000, 626390000, 626490000]
    for (name, digest), root, seed in zip(QUALIFICATION_HASHES.items(), roots, seeds, strict=True):
        directory = Path(root) / name
        raw = (directory / 'recipe.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise RuntimeError(f'{name}: qualification recipe identity mismatch')
        recipe, _ = _read(directory)
        if recipe['seed0'] != seed or recipe['deals'] != 12:
            raise RuntimeError(f'{name}: qualification population mismatch')
        summary = json.loads((directory / 'summary.json').read_text())
        wall = summary.get('wall_seconds')
        if not isinstance(wall, (int, float)) or not 0 < wall <= 3600:
            raise RuntimeError(f'{name}: missing or invalid qualification wall time')
        evidence[name] = {'recipe_sha256': digest, 'wall_seconds': wall}
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source', 'python', 'gen4-checkpoint', 'gen3-checkpoint',
                'production-checkpoint', 'out', 'joint-qualification',
                'gen4-qualification', 'gen3-qualification'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    # The release gate is shared with the four-model reader. Any unfrozen pin
    # refuses before qualification/model reads or host probes, even for --run.
    evidence = qualification_gate(args.joint_qualification, args.gen4_qualification,
                                  args.gen3_qualification)
    plan = packet(args.python.absolute(), args.gen4_checkpoint.resolve(),
                  args.gen3_checkpoint.resolve(), args.production_checkpoint.resolve(),
                  args.out.resolve())
    if sys.platform != 'linux':
        raise RuntimeError('Linux supervisor required')
    source, output = args.source.resolve(), args.out.resolve()
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True)
    if head != supervisor.REFERENCE_SOURCE or dirty:
        raise RuntimeError('clean frozen runtime source required')
    for path, digest in ((args.gen4_checkpoint, supervisor.GEN4_CHECKPOINT_SHA256),
                         (args.gen3_checkpoint, supervisor.GEN3_CHECKPOINT_SHA256),
                         (args.production_checkpoint, supervisor.PRODUCTION_SHA256)):
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError('checkpoint mismatch')
    if output.exists() or not output.parent.is_dir():
        raise RuntimeError('fresh output under existing parent required')
    if any(path.exists() for path in supervisor.LOCKS):
        raise RuntimeError('peer lane/screen reservation held')
    supervisor.resource_guard(output.parent)
    plan.update(launch_hold=False, qualification_evidence=evidence,
                mode='full-screen', arm_timeout_seconds=21600)
    print(json.dumps(plan, indent=2))
    if not args.run:
        return 0
    env = {key: value for key, value in os.environ.items()
           if key in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR')}
    env.update(PYTHONPATH=str(source / 'server'), PYTHONDONTWRITEBYTECODE='1',
               OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
               VECLIB_MAXIMUM_THREADS='1', SHENGJI_REQUIRE_VOIDS='1')
    acquired = []
    previous = signal.signal(signal.SIGTERM, supervisor.interrupted)
    try:
        for lock in supervisor.LOCKS:
            lock.mkdir()
            acquired.append(lock)
            (lock / 'pid').write_text(str(os.getpid()) + '\n')
        supervisor.resource_guard(output.parent)
        output.mkdir()
        (output / 'launch-plan.json').write_text(json.dumps(plan, indent=2) + '\n')
        for arm in plan['arms']:
            supervisor.resource_guard(output.parent)
            supervisor.run_arm(arm['command'], env=env, cwd=source / 'server',
                               log=output / (arm['name'] + '.log'), seconds=21600)
            supervisor.validate_summary(output / arm['name'] / 'summary.json', expected=800)
    finally:
        for lock in reversed(acquired):
            if (lock / 'pid').read_text().strip() == str(os.getpid()):
                (lock / 'pid').unlink()
                lock.rmdir()
        signal.signal(signal.SIGTERM, previous)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
