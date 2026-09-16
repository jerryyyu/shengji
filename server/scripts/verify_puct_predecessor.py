"""Verify the exact completed G1 invocation after transient-unit unloading.

This is one named recovery, not a generic permission to ignore missing units.
All output, recipe, asset, host and reservation checks remain in the launcher.
"""
import json
import subprocess

UNIT = 'codex-puct-g1-sequential-20260916.service'
INVOCATION = '8f2cd379dd4a4d9eb989ec1637b97f27'
MACHINE = '6334bc24c695429a9e5a1dd3ed08c889'
BOOT = 'cab55f68a5294be5b4e02e3ff918a0d8'


def verify(rows):
    relevant = [r for r in rows if r.get('UNIT') == UNIT or
                r.get('_SYSTEMD_UNIT') == UNIT]
    if not relevant:
        raise ValueError('missing predecessor journal')
    # A later invocation (successful or not) invalidates this one-off receipt.
    for row in relevant:
        invocation = row.get('INVOCATION_ID', row.get('_SYSTEMD_INVOCATION_ID'))
        if (invocation != INVOCATION or row.get('_MACHINE_ID') != MACHINE or
                row.get('_BOOT_ID') != BOOT):
            raise ValueError('unexpected predecessor invocation or host')
    start, done, success = [], [], []
    for row in relevant:
        stamp = int(row['__MONOTONIC_TIMESTAMP'])
        manager = row.get('_PID') == '1' and row.get('_UID') == '0'
        if (manager and row.get('JOB_TYPE') == 'start' and
                row.get('JOB_RESULT') == 'done'):
            start.append(stamp)
        if (row.get('_PID') == '1183266' and row.get('_UID') == '0' and
                row.get('_SYSTEMD_UNIT') == UNIT and
                row.get('MESSAGE') == 'G1 SEQUENTIAL LADDER DONE'):
            done.append(stamp)
        if (manager and row.get('UNIT') == UNIT and
                row.get('CODE_FUNC') == 'unit_log_success' and
                row.get('MESSAGE_ID') == '7ad2d189f7e94e70a38c781354912448'):
            success.append(stamp)
    if not (len(start) == len(done) == len(success) == 1 and
            start[0] < done[0] < success[0]):
        raise ValueError('missing or inconsistent successful completion receipt')


def main():
    output = subprocess.run(
        ['journalctl', '-u', UNIT, '--since', '2026-09-16 06:03:00 UTC',
         '-o', 'json', '--no-pager'], check=True, capture_output=True, text=True,
        timeout=20)
    verify([json.loads(line) for line in output.stdout.splitlines() if line])
    print(f'Verified journal completion: {UNIT} invocation={INVOCATION}')


if __name__ == '__main__':
    main()
