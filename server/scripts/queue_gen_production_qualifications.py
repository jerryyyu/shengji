#!/usr/bin/env python3
"""Guarded one-shot successor for the gen4 then gen3 qualifications.

The default is status-only.  ``--run`` waits for the exact predecessor and then
invokes each already-reviewed qualification launcher once, in order.  This
supervisor never restarts, kills, or retries a predecessor or successor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


UNIT = 'codex-joint-production-screen-20260921.service'
EXPECTED_INVOCATION = 'db9f4e7ce92d42cfb25a33a387421a95'
EXPECTED_BOOT_ID = 'cab55f68a5294be5b4e02e3ff918a0d8'
SYSTEMD_MANAGER_SCOPE = 'init.scope'
UNIT_LOG_SUCCESS = '7ad2d189f7e94e70a38c781354912448'
POLL_SECONDS = 30
OBSERVE_SECONDS = 12 * 60 * 60
OBSERVE_COMMAND_SECONDS = 30

PREDECESSOR_OUTPUT = Path('/root/codex-joint-production-screen-20260921')
PREDECESSOR_DEV = 2049
PREDECESSOR_INO = 1055897
PREDECESSOR_PLAN_SHA256 = 'df8b63f2d9c34143ffa7c363f508111ac71971ff2a3a0cda6119adccf887f1b8'
PREDECESSOR_ARMS = ('JS_M1_W64_K8', 'JS_G1_W64_K8')

PYTHON = Path('/root/gen-hybrid/server/.venv/bin/python')
RUNTIME_SOURCE = Path('/root/codex-policy-source-20260920')
PRODUCTION_CHECKPOINT = Path('/root/codex-production-js-m1-0d17fd03.npz')

GEN4 = {
    'name': 'gen4',
    'source': Path('/root/codex-gen4-production-launcher-20260921'),
    'head': '83b0047f00300c6d903290768a98ef2b5cbb7a97',
    'checkpoint': Path('/root/claude-gen4r1.pt'),
    'output': Path('/root/codex-gen4-production-qualify-20260921'),
    'suite': 'gen4-production-qualify',
}
GEN3 = {
    'name': 'gen3',
    'source': Path('/root/codex-gen3-production-launcher-20260921'),
    'head': 'f8c422c3af87cc39c5ab71dca4650c56dc47551f',
    'checkpoint': Path('/root/head8k/gen3warm-best.pt'),
    'output': Path('/root/codex-gen3-production-qualify-20260921'),
    'suite': 'gen3-production-qualify',
}


class QueueRefusal(RuntimeError):
    """A fail-closed observation, identity, or successor refusal."""


def _fields(text: str) -> dict[str, str]:
    fields = {}
    for line in text.splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            fields[key] = value
    return fields


def _run(command: list[str], *, timeout: float | None = OBSERVE_COMMAND_SECONDS,
         capture: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        kwargs = dict(check=False, text=True, timeout=timeout)
        if capture:
            kwargs['capture_output'] = True
        return subprocess.run(command, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QueueRefusal(f'command observation failed: {command[0]}') from exc


def service_snapshot() -> dict[str, str]:
    result = _run(['systemctl', 'show', UNIT, '--no-pager',
                   '-p', 'LoadState', '-p', 'InvocationID', '-p', 'ActiveState',
                   '-p', 'SubState', '-p', 'Result', '-p', 'ExecMainStatus', '-p', 'MainPID'])
    fields = _fields(result.stdout)
    if result.returncode and fields.get('LoadState') != 'not-found':
        raise QueueRefusal('systemd predecessor observation failed')
    if not fields:
        raise QueueRefusal('systemd predecessor observation was empty')
    fields.setdefault('LoadState', 'not-found' if result.returncode else '')
    if fields.get('LoadState') == 'not-found':
        fields.setdefault('InvocationID', '')
        fields.setdefault('ActiveState', 'inactive')
        fields.setdefault('Result', '')
        fields.setdefault('ExecMainStatus', '')
        fields.setdefault('MainPID', '0')
    return fields


def journal_proves_unloaded_success() -> bool:
    result = _run(['journalctl', '-u', UNIT,
                   f'INVOCATION_ID={EXPECTED_INVOCATION}', '-o', 'json', '--no-pager'])
    if result.returncode:
        raise QueueRefusal('predecessor success journal unavailable')
    for line in result.stdout.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (str(entry.get('_PID', '')) == '1'
                and entry.get('UNIT') == UNIT
                and entry.get('_SYSTEMD_UNIT') == SYSTEMD_MANAGER_SCOPE
                and entry.get('INVOCATION_ID') == EXPECTED_INVOCATION
                and entry.get('_BOOT_ID') == EXPECTED_BOOT_ID
                and entry.get('MESSAGE_ID') == UNIT_LOG_SUCCESS):
            return True
    raise QueueRefusal('predecessor success journal proof mismatch')


def current_boot_id() -> str:
    try:
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip().replace('-', '')
    except OSError as exc:
        raise QueueRefusal('current boot identity unavailable') from exc


def _terminal_status_ok(snapshot: dict[str, str]) -> bool:
    return (snapshot.get('ActiveState') == 'inactive'
            and snapshot.get('MainPID') == '0'
            and snapshot.get('Result') == 'success'
            and snapshot.get('ExecMainStatus') == '0')


def _unloaded_status_ok(snapshot: dict[str, str]) -> bool:
    return (snapshot.get('ActiveState') == 'inactive'
            and snapshot.get('MainPID', '') in ('', '0')
            and snapshot.get('Result', '') in ('', 'success')
            and snapshot.get('ExecMainStatus', '') in ('', '0'))


def classify_snapshot(snapshot: dict[str, str]) -> str:
    if current_boot_id() != EXPECTED_BOOT_ID:
        raise QueueRefusal('predecessor is from a different boot')
    invocation = snapshot.get('InvocationID', '')
    state = snapshot.get('ActiveState', '')
    if invocation and invocation != EXPECTED_INVOCATION:
        raise QueueRefusal('predecessor invocation was replaced')
    if state in ('failed', 'refused', 'error') or snapshot.get('Result') in (
            'failed', 'refused', 'error', 'exit-code', 'signal', 'timeout'):
        raise QueueRefusal('predecessor failed or was refused')
    if (invocation == EXPECTED_INVOCATION
            and snapshot.get('MainPID') == '0'
            and snapshot.get('Result') == 'success'
            and snapshot.get('ExecMainStatus') == '0'
            and (state == 'inactive' or
                 (state == 'active' and snapshot.get('SubState') == 'exited'))):
        return 'success'
    if state in ('active', 'activating', 'deactivating'):
        if not invocation:
            raise QueueRefusal('active predecessor has no pinned invocation')
        return 'running'
    if invocation == EXPECTED_INVOCATION:
        if not _terminal_status_ok(snapshot):
            raise QueueRefusal('predecessor was not terminal success')
        return 'success'
    # systemd may unload a successful transient unit.  Missing/cleared identity
    # is accepted only with an inactive/no-main-pid state and journal proof.
    if (not invocation and snapshot.get('LoadState') in ('not-found', '')):
        if not _unloaded_status_ok(snapshot):
            raise QueueRefusal('unloaded predecessor has a live or failed state')
        journal_proves_unloaded_success()
        return 'success'
    raise QueueRefusal('predecessor identity missing or replacement detected')


def wait_for_predecessor(*, deadline: float | None = None) -> dict[str, str]:
    deadline = time.monotonic() + OBSERVE_SECONDS if deadline is None else deadline
    while True:
        snapshot = service_snapshot()
        status = classify_snapshot(snapshot)
        if status == 'success':
            return snapshot
        if time.monotonic() >= deadline:
            raise QueueRefusal('predecessor observation deadline exceeded')
        try:
            time.sleep(POLL_SECONDS)
        except (OSError, KeyboardInterrupt) as exc:
            raise QueueRefusal('predecessor observation interrupted') from exc


def validate_predecessor_artifacts() -> None:
    try:
        identity = PREDECESSOR_OUTPUT.stat()
    except OSError as exc:
        raise QueueRefusal('predecessor output is missing') from exc
    if (identity.st_dev, identity.st_ino) != (PREDECESSOR_DEV, PREDECESSOR_INO):
        raise QueueRefusal('predecessor output directory replaced')
    try:
        plan_hash = hashlib.sha256(
            (PREDECESSOR_OUTPUT / 'launch-plan.json').read_bytes()).hexdigest()
    except OSError as exc:
        raise QueueRefusal('predecessor launch plan is missing') from exc
    if plan_hash != PREDECESSOR_PLAN_SHA256:
        raise QueueRefusal('predecessor launch plan differs')
    for arm in PREDECESSOR_ARMS:
        try:
            summary = json.loads((PREDECESSOR_OUTPUT / arm / 'summary.json').read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise QueueRefusal(f'predecessor summary missing or invalid: {arm}') from exc
        if (summary.get('expected') != 800 or summary.get('complete') != 800
                or summary.get('errors') != []
                or summary.get('aggregation_error') is not None):
            raise QueueRefusal(f'predecessor arm did not seal cleanly: {arm}')


def validate_launcher(config: dict) -> None:
    result = _run(['git', '-C', str(config['source']), 'rev-parse', 'HEAD'])
    if result.returncode or result.stdout.strip() != config['head']:
        raise QueueRefusal(f"{config['name']} launcher HEAD differs")
    result = _run(['git', '-C', str(config['source']), 'status', '--porcelain'])
    if result.returncode or result.stdout:
        raise QueueRefusal(f"{config['name']} launcher is dirty")


def launcher_command(config: dict) -> list[str]:
    return [str(PYTHON), str(config['source'] / 'server/scripts/policy_abc_launcher.py'),
            '--source', str(RUNTIME_SOURCE), '--python', str(PYTHON),
            '--checkpoint', str(config['checkpoint']), '--out', str(config['output']),
            '--suite', config['suite'], '--qualify', '--production-worlds', '64',
            '--production-checkpoint', str(PRODUCTION_CHECKPOINT), '--run']


def run_successor(config: dict) -> None:
    validate_launcher(config)
    result = _run(launcher_command(config), timeout=None, capture=False)
    if result.returncode:
        raise QueueRefusal(f"{config['name']} qualification launcher failed")


def status() -> dict[str, str]:
    return service_snapshot()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true',
                        help='wait for the pinned predecessor and launch gen4 then gen3')
    args = parser.parse_args(argv)
    if not args.run:
        print(json.dumps(status(), sort_keys=True))
        return 0
    wait_for_predecessor()
    validate_predecessor_artifacts()
    # Re-read immediately before gen4, then validate gen3 only after gen4 exits.
    if classify_snapshot(service_snapshot()) != 'success':
        raise QueueRefusal('predecessor was not terminal before gen4')
    run_successor(GEN4)
    if classify_snapshot(service_snapshot()) != 'success':
        raise QueueRefusal('predecessor was not terminal before gen3')
    run_successor(GEN3)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
