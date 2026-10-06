"""Bounded S11 shard transport building blocks; not a launcher or RELEASE.

Call only inside the reviewed guarded input controller after its durable claim.
The manifest is already pinned and admitted to the fixed 64-file staging plan.
Transport success is not admission: the input reader still verifies every SHA.
"""
from pathlib import Path
import os
import re
import shlex
import subprocess

from shengji.luna.atomic_io import publish_exclusive_bytes


SSH = '/usr/bin/ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes -o ControlMaster=no -o ControlPath=none -o ControlPersist=no'
SOURCE = 'shengji-perf:/root/traj-out/runPVC8/'


def transfer_manifest(path, *, log):
    """Pull at most 8MiB+1 from the fixed frame; caller authenticates before parse.

    Existing outer claim/guard required, exactly as for transfer_shards. Leave
    any partial behind on failure. No shell interpolation or configurable
    remote path; the reviewed host alias/host-key policy is preserved.
    """
    command = shlex.split(SSH) + ['shengji-perf',
        '/usr/bin/head -c 8388609 -- /root/traj-out/runPVC8/manifest.json']
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    with os.fdopen(fd, 'wb') as output:
        subprocess.run(command, check=True, stdout=output, stderr=log)
        output.flush()
        os.fsync(output.fileno())
    # Excess size remains on disk for explicit disposition, never truncated
    # into a different supposedly valid manifest.
    if Path(path).stat().st_size > 8 << 20:
        raise ValueError('transferred manifest exceeds admitted ceiling')


def files_from_bytes(plan):
    files = plan['files']
    if type(files) is not list or len(files) != 64:
        raise ValueError('fixed 64-file staging plan required')
    paths = []
    for index, item in enumerate(files):
        if (type(item) is not dict or set(item) != {'path', 'bytes', 'sha256', 'draw_index'} or
                type(item['path']) is not str or
                not re.fullmatch(r'shards/cluster-[0-9]{6,}\.jsonl', item['path']) or
                type(item['bytes']) is not int or not 0 < item['bytes'] <= 4 << 20 or
                type(item['draw_index']) is not int or item['draw_index'] != index or
                type(item['sha256']) is not str or
                not re.fullmatch('[0-9a-f]{64}', item['sha256'])):
            raise ValueError('staging file entry refused')
        paths.append(item['path'])
    if len(set(paths)) != 64:
        raise ValueError('duplicate staging path')
    # Paths are fixed ASCII without newlines, so no --from0 compatibility need.
    return ('\n'.join(paths) + '\n').encode('ascii')


def rsync_command(source, files_from, destination):
    """Shared exact flags, also exercised against a local synthetic source."""
    return ['/usr/bin/rsync', '--relative', '--partial', '--no-links', '--no-specials',
            '--no-devices', '--max-size=4194304', '--timeout=60',
            '--files-from=' + str(files_from), '-e', SSH,
            '--', source, str(destination) + '/']


def transfer_shards(plan, files_from, destination, *, log):
    """One transfer only. Outer guard owns wall/RSS/parent-death/cleanup.

    No archive/recursive/link/device/delete flags, retries or permission to
    advance after a skipped/missing file. Destination must be fresh/private as
    enforced by the outer packet. Do not invoke this directly for a real pull.
    """
    files_from = Path(files_from)
    publish_exclusive_bytes(files_from, files_from_bytes(plan))
    subprocess.run(rsync_command(SOURCE, files_from, destination),
                   check=True, stdout=log, stderr=log)
