"""Capture configs from the real queue without opening an output or running games."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

SERVER = Path(__file__).resolve().parents[2] / 'server'


def probe_configs(plan):
    configs = {}
    for side, arm in plan['arms'].items():
        from launcher import _clean_env
        env = _clean_env(arm, SERVER.parent)
        windows = [w for w in plan['windows'] if w['side'] == side]
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--probe'],
                                input=json.dumps(windows), text=True, capture_output=True,
                                cwd=SERVER, env=env, timeout=60, check=False)
        if result.returncode:
            raise ValueError(f'config probe failed: {result.stderr[-4000:]}')
        captured = json.loads(result.stdout)
        if set(captured) != {w['output'] for w in windows}:
            raise ValueError('config probe inventory drift')
        for config in captured.values():
            if (config['arm_policy'] != arm['name']
                    or config['arm_policy_identity'] != arm['identity']):
                raise ValueError('config probe arm drift')
        if configs.keys() & captured.keys():
            raise ValueError('duplicate config probe output')
        configs.update(captured)
    return configs


def worker():
    from shengji.train import cwv_screen_queue as queue
    screen = queue.screen
    configs = {}

    class Captured(Exception):
        pass

    def capture(path, config):
        configs[str(path)] = config
        raise Captured

    # Stop at the config publication boundary, before resume reads or games.
    with (patch.object(screen, 'screen_output_lock', lambda path: contextlib.nullcontext()),
          patch.object(screen, 'bind_output_config', capture),
          patch.object(screen, '_run_pending', side_effect=AssertionError('game dispatch forbidden')),
          patch.object(screen, 'run_cluster', side_effect=AssertionError('game execution forbidden')),
          contextlib.redirect_stdout(io.StringIO())):
        for window in json.load(sys.stdin):
            try:
                queue.main(window['argv'])
            except Captured:
                continue
            raise ValueError('queue did not reach config capture boundary')
    print(json.dumps(configs, sort_keys=True))


if __name__ == '__main__':
    if sys.argv[1:] != ['--probe']:
        raise SystemExit('only --probe is supported; no run mode')
    worker()
