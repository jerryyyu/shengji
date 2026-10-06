"""Single scheduled public-root collection with no automatic failed-root retry.

Admission, scheduling, refusal ceilings and launch authority remain external.
This wrapper accepts an already admitted public fixture, never a private shard.
"""
import fcntl
import hashlib
import os
from pathlib import Path
import stat

from .s11_collection import collect_s11_fixture
from .s11_persistence import _context, _encode, load_s11_root, save_s11_root
from ..luna.atomic_io import publication_slot_occupied, publish_exclusive_bytes


def _require_start(path, expected):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != 0o400 or before.st_nlink != 1
                or before.st_size != len(expected)):
            raise ValueError('started record identity mismatch')
        raw = stream.read(len(expected) + 1)
        after = os.fstat(stream.fileno())
    if raw != expected or any(getattr(before, key) != getattr(after, key) for key in
            ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')):
        raise ValueError('started record context or identity mismatch')


def collect_s11_once(directory, bot_factory, fixture, *, packet_sha256, seed,
                     fill_seed=0, check_budget=None):
    """Reuse a completion or collect once; started-without-completion refuses.

    Existing failure/started markers are never removed, reset or retried.
    The enclosing run directory must already exist under exclusive ownership.
    The root lock additionally prevents simultaneous same-root collection.
    """
    context = _context(packet_sha256, fixture, seed, fill_seed)
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('existing owned run directory required')
    name = hashlib.sha256(fixture.id.encode()).hexdigest()
    root = directory / name
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('regular root directory required')
    # Persist the root directory name itself, not only files created inside it.
    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    lock = os.open(root / 'owner.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError('root lock identity mismatch')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        completed, started, failed = (root / name for name in ('completed.json', 'started.json', 'failed.json'))
        start_bytes = _encode(dict(schema='s11-root-attempt-v1', status='started', context=context))
        saved = load_s11_root(completed, packet_sha256=packet_sha256,
                              fixture=fixture, seed=seed, fill_seed=fill_seed)
        if saved is not None:
            _require_start(started, start_bytes)
            if publication_slot_occupied(failed):
                raise ValueError('contradictory completed and failed root')
            return saved
        if publication_slot_occupied(started) or publication_slot_occupied(failed):
            raise ValueError('started root has no completion; explicit disposition required')
        if check_budget is not None:
            check_budget()
        publish_exclusive_bytes(started, start_bytes)
        try:
            result = collect_s11_fixture(bot_factory, fixture, seed=seed,
                fill_seed=fill_seed, check_budget=check_budget)
            save_s11_root(completed, result, packet_sha256=packet_sha256, fixture=fixture)
        except Exception as exc:
            # If publication failed after linking a complete final, leave its
            # recovery to load_s11_root instead of creating contradictory state.
            if not publication_slot_occupied(completed):
                try:
                    publish_exclusive_bytes(failed, _encode(dict(
                        schema='s11-root-attempt-v1', status='failed', context=context,
                        error_type=type(exc).__name__, reason=str(exc))))
                except Exception as journal_error:
                    exc.add_note(f'Failure journal could not be published: {type(journal_error).__name__}')
            raise
        return result
    finally:
        os.close(lock)
