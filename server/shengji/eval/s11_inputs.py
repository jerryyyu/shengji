"""Authenticated S11 scheduled input reader; no model or exposure authority.

Call only after the real population's exposure/reader gates have been resolved.
Returns every scheduled slot, including failures, with no replacement draws.
Only each valid slot's `fixture` may be passed to model-facing collection.
"""
import os
from pathlib import Path
import stat

from .s11_manifest import select_manifest_shards
from .s11_shard import mirror_play_rows
from .s11_selection import select_ply
from .s11_reconstruction import reconstruct_s11_trajectory
from .s11_public_view import public_s11_fixture


def _read_shard(root, item):
    # The manifest parser has already required this canonical relative path.
    expected = f'shards/cluster-{item.cluster:06d}.jsonl'
    if item.path != expected:
        raise ValueError('noncanonical shard path')
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(root, directory_flags)
    try:
        shard_dir = os.open('shards', directory_flags, dir_fd=root_fd)
        try:
            fd = os.open(Path(expected).name, os.O_RDONLY | os.O_NOFOLLOW |
                         os.O_NONBLOCK, dir_fd=shard_dir)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size != item.byte_count:
                    raise ValueError('shard file type or byte count mismatch')
                with os.fdopen(fd, 'rb', closefd=False) as handle:
                    raw = handle.read(item.byte_count + 1)
                if len(raw) != item.byte_count:
                    raise ValueError('shard changed size during read')
                return raw
            finally:
                os.close(fd)
        finally:
            os.close(shard_dir)
    finally:
        os.close(root_fd)


def read_s11_inputs(manifest, *, sha256, root, fill_seed=0):
    """Authenticate the complete schedule before opening any selected shard.

    Invalid manifest aborts before I/O. Per-shard input errors preserve their
    original slot. Unexpected runtime/programming errors propagate, rather
    than being relabelled as scientific refusals. No sidecars are read.
    """
    if type(fill_seed) is not int or fill_seed < 0:
        raise ValueError('nonnegative integer fill seed required')
    schedule = select_manifest_shards(manifest, sha256=sha256)
    results = []
    for item in schedule:
        root_id = f's11-{sha256}-draw-{item.draw_index:02d}'
        stage = 'shard'
        try:
            raw = _read_shard(root, item)
            rows = mirror_play_rows(raw, sha256=item.sha256,
                record_count=item.record_count, run_id=item.run_id,
                cluster=item.cluster, seed=item.seed, mirror=item.mirror)
            stage = 'terminal'
            reconstruct_s11_trajectory(rows, 0)
            ply = select_ply(sha256, item.seed, item.mirror, len(rows))
            stage = 'public-projection'
            fixture = public_s11_fixture(rows, ply, root_id=root_id,
                                         fill_seed=fill_seed)
        except (OSError, ValueError) as exc:
            results.append(dict(root_id=root_id, draw_index=item.draw_index,
                status='refused', stage=stage,
                reason=f'{type(exc).__name__}: {exc}'))
        else:
            results.append(dict(root_id=root_id, draw_index=item.draw_index,
                status='valid', selected_ply=ply, fixture=fixture))
    return results
