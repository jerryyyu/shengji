"""Unarmed screen-worker admission: construct bots, never play a game."""
import json
import os
from pathlib import Path
import subprocess
import sys


SERVER = Path(__file__).resolve().parents[2] / 'server'


def admit_pair(envs, *, profile='served'):
    from recipe import build_pair
    from shengji.train.cwv_shortlist_screen import _policy_identity

    expected = [dict(name=name, identity=_policy_identity(bot))
                for name, bot in build_pair(envs, profile=profile)]
    admitted = []
    for env, want in zip(envs, expected, strict=True):
        from launcher import _clean_env
        explicit = {**env, 'SHENGJI_FAST': env.get('SHENGJI_FAST', os.environ.get('SHENGJI_FAST', '0'))}
        child_env = _clean_env({'environment': explicit}, SERVER.parent)
        result = subprocess.run(
            [sys.executable, '-B', str(Path(__file__).resolve()), '--worker-probe'],
            input=json.dumps(want), text=True, capture_output=True, check=False,
            cwd=SERVER, env=child_env, timeout=60)
        if result.returncode:
            raise ValueError(f'screen probe failed: {result.stderr[-4000:]}')
        actual = json.loads(result.stdout)
        if actual != want:
            raise ValueError('screen worker admission identity drift')
        admitted.append(actual)
    return admitted


def worker_probe():
    from shengji.ai.registry import make_bot
    from shengji.train import cwv_shortlist_screen as screen
    from shengji.train.screen_deadline import DeadlineSession

    expected = json.load(sys.stdin)
    bot = make_bot(expected['name'], seed=17)
    actual = dict(name=bot.policy_name, identity=screen._policy_identity(bot))
    if actual != expected:
        raise ValueError('fresh-process registry identity drift')
    config = dict(arm='policy', arm_policy=actual['name'],
                  arm_policy_identity=actual['identity'])
    session = DeadlineSession(screen._deadline_side)
    try:
        session.register(config, 'arm', 17)
    finally:
        session.close()
    print(json.dumps(actual, sort_keys=True))


if __name__ == '__main__':
    if sys.argv[1:] != ['--worker-probe']:
        raise SystemExit('only --worker-probe is supported; no run mode')
    worker_probe()
