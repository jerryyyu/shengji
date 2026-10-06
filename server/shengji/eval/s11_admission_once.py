"""One admitted input attempt; no launch, exposure or runtime authority.

An external reviewed wrapper must own the host and enforce wall/memory limits.
It pins this source/runtime, manifest digest and packet before calling. This
boundary records intent before raw access, never retries, and emits no output.
"""
import os
import re
import stat

from .s11_input_bundle import publish_s11_input_bundle
from .s11_inputs import read_s11_inputs
from .s11_manifest import select_manifest_shards
from .s11_persistence import _encode
from .s11_schedule import _owned_directory
from ..luna.atomic_io import publication_slot_occupied, publish_exclusive_bytes


def plan_s11_staging(manifest, *, manifest_sha256):
    """Plan the fixed draw's transfer, without opening shards or emitting data.

    These conservative transport ceilings are part of the proposed packet,
    not adaptive defaults. Exceeding one requires a new review, not a redraw.
    The caller persists the supplied manifest privately and gives only these
    canonical paths to bounded rsync (no symlinks/devices/special files).
    Transport success is NOT admission: the reader must still authenticate
    every selected shard and reconstruct its terminal/public state.
    """
    if type(manifest) is not bytes or len(manifest) > 8 << 20:
        raise ValueError('staging manifest exceeds 8MiB ceiling')
    selected = select_manifest_shards(manifest, sha256=manifest_sha256)
    if any(s.byte_count > 4 << 20 for s in selected):
        raise ValueError('selected shard exceeds 4MiB staging ceiling; no replacement')
    files = [dict(path=s.path, sha256=s.sha256, bytes=s.byte_count,
                  draw_index=s.draw_index) for s in selected]
    return dict(schema='s11-staging-plan-v1', manifest_sha256=manifest_sha256,
                manifest_bytes=len(manifest), files=files,
                shard_bytes=sum(s.byte_count for s in selected),
                max_manifest_bytes=8 << 20, max_shard_bytes=4 << 20,
                max_total_shard_bytes=256 << 20)


def _manifest(path, max_manifest_bytes):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_manifest_bytes:
            raise ValueError('manifest file type/size refused')
        with os.fdopen(fd, 'rb', closefd=False) as handle:
            raw = handle.read(max_manifest_bytes + 1)
        after = os.fstat(fd)
        if (len(raw) != before.st_size or any(getattr(before, k) != getattr(after, k)
                for k in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))):
            raise ValueError('manifest changed during read')
        return raw
    finally:
        os.close(fd)


def admit_s11_inputs_once(manifest_path, root, directory, *, manifest_sha256,
                          packet_sha256, max_manifest_bytes):
    """Return an outcome-free receipt, or refuse without implicit resumption.

    The packet binds all paths and the explicit manifest byte ceiling. A fresh
    existing owned empty directory is required. Concurrent callers compete for
    an O_EXCL marker; even a crashed/empty marker forbids another raw read.
    Unexpected failures are preserved as a fixed diagnostic without exception
    text, which might contain raw records. SIGKILL leaves the start marker.
    """
    if any(type(p) is not str or not re.fullmatch('[0-9a-f]{64}', p)
           for p in (manifest_sha256, packet_sha256)):
        raise ValueError('admission SHA256 pins required')
    if type(max_manifest_bytes) is not int or not 0 < max_manifest_bytes <= 64 << 20:
        raise ValueError('manifest byte ceiling must be in 1..64MiB')
    directory = _owned_directory(directory)
    if any(directory.iterdir()):
        raise ValueError('admission directory occupied; explicit disposition required')
    marker = directory / 'started.json'
    # Do not use recoverable partial publication for the exclusive claim:
    # two identical concurrent claims must not both succeed.
    context = dict(schema='s11-input-attempt-v1', packet_sha256=packet_sha256,
                   manifest_sha256=manifest_sha256)
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(_encode(context))
        handle.flush()
        os.fsync(handle.fileno())
    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    phase = 'manifest'
    try:
        raw = _manifest(manifest_path, max_manifest_bytes)
        phase = 'staging-plan'
        plan_s11_staging(raw, manifest_sha256=manifest_sha256)
        phase = 'input-reader'
        slots = read_s11_inputs(raw, sha256=manifest_sha256, root=root, fill_seed=0)
        phase = 'bundle'
        receipt = publish_s11_input_bundle(slots, directory / 'bundle.json',
            manifest_sha256=manifest_sha256, packet_sha256=packet_sha256)
        phase = 'receipt'
        publish_exclusive_bytes(directory / 'receipt.json', _encode(receipt))
        return receipt
    except Exception:
        # Never print or persist raw exception values, scores or outcome fields.
        # A bundle without a receipt is not permission to rerun admission.
        failure = directory / 'failed.json'
        try:
            if not publication_slot_occupied(failure):
                publish_exclusive_bytes(failure, _encode(dict(context,
                    status='failed', phase=phase,
                    reason='input admission incomplete; explicit disposition required')))
        except Exception:
            # Keep the durable start marker even when failure recording fails.
            # Do not chain a recording error to the original private exception.
            pass
    # Raise outside the handler: `from None` alone hides traceback rendering
    # but retains the private exception in __context__ for error serializers.
    raise ValueError('S11 input admission failed; inspect sealed operational artifacts')
