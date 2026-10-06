"""Lazy, fixed-recipe S11 factory over one checked outcome export.

Caller establishes packet RELEASE, admitted inputs, guarded runtime and host
ownership before invoking this factory. It is not a launch boundary. Only the
canonical served loader opens weights; every returned bot is a fresh snapshot.
"""
import copy
from pathlib import Path
import re
import stat

from ..train import pv_search_policy as pv
from .s11_collection import _snapshot


def _pin(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('full SHA256 required')
    return value


def _stamp(path):
    if not path.is_absolute() or path.resolve() != path or path.suffix != '.npz':
        raise ValueError('canonical absolute NumPy export path required')
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o222
            or not 0 < info.st_size <= 512 << 20):
        raise ValueError('frozen regular export required')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode)


def make_s11_model_factory(checkpoint, *, sha256, source_checkpoint_sha256):
    """Load on first call only in a single-threaded worker, then copy snapshots.

    Exact fixed recipe: outcome head/encoder2, W64/K8/cap4000/batch128,
    seed0, release38 div/rc/tb/la, no extra rules/tree/prior override. Weights
    remain shared read-only through their existing deepcopy protocol; each bot
    owns its sampler, refusal ledger, mutable evaluator counters and telemetry.
    The dedicated frozen file is stat-checked on every call, never rehashed per
    root. A failed load poisons this factory instead of silently retrying it.
    """
    _pin(sha256)
    _pin(source_checkpoint_sha256)
    path = Path(checkpoint)
    stamp = _stamp(path)
    template, failed = None, False

    def build():
        nonlocal template, failed
        if failed:
            raise ValueError('S11 model factory failed; explicit disposition required')
        try:
            if _stamp(path) != stamp:
                raise ValueError('S11 frozen export changed')
            if template is None:
                candidate = pv.make_pv_search_bot(str(path), sha256=sha256,
                    worlds=64, candidates=8, cap=4000, batch_size=128, seed=0,
                    threads=1, serving_budget_seconds=None, tree=None,
                    refusal_constraints=True, refusal_event_complete=False,
                    admission_diversity=True, admit_forced_single=False,
                    tiebreak_points=True, adaptive_k=False, lead_anchor=True,
                    lead_tiebreak_prior=False, doomed_throw_swap=False)
                evaluator = candidate.evaluator
                if (type(candidate) is not pv.PVSearchBot or candidate.version != 2
                        or evaluator.backend != 'numpy' or evaluator.value_head != 'outcome'
                        or evaluator.checkpoint_sha256 != sha256
                        or evaluator.model.source_checkpoint_sha256 != source_checkpoint_sha256
                        or candidate.prior_checkpoint is not None
                        or candidate.prior_sha256 is not None):
                    raise ValueError('S11 model/export identity mismatch')
                _snapshot(candidate, 0)
                if _stamp(path) != stamp:
                    raise ValueError('S11 frozen export changed during loading')
                template = candidate
            result = copy.deepcopy(template)
            if _snapshot(result, 0) != _snapshot(template, 0):
                raise ValueError('S11 model snapshot drift')
            if _stamp(path) != stamp:
                raise ValueError('S11 frozen export changed during snapshot')
            return result
        except Exception:
            failed = True
            raise

    return build
