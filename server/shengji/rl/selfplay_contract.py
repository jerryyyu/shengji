"""Small executable contracts shared by self-play RL experiments.

The historical DMC2 run mixed two independent correctness boundaries into its
training loop: acting-team target signs and mutable actor checkpoint paths.
Keep those rules here so future Suphx/DouZero microbaselines cannot each invent
another subtly different implementation.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


DMC2_REWARD_SCHEMA = "dmc2-clipped-level-possession-v1"


def role_sign(acting_is_attacker: bool) -> int:
    """Map an attacker-perspective scalar into the acting team's perspective."""
    return 1 if acting_is_attacker else -1


def signed_return(attacker_return, acting_is_attacker: bool):
    return role_sign(acting_is_attacker) * attacker_return


def signed_oracle_residual(attacker_return, attacker_baseline,
                           acting_is_attacker: bool):
    """Return and baseline must be transformed by the same role sign.

    For defenders this is ``-return - (-baseline)``, not the historical
    ``-return - baseline`` defect.
    """
    return signed_oracle_residual_by_sign(
        attacker_return, attacker_baseline, role_sign(acting_is_attacker))


def signed_oracle_residual_by_sign(attacker_return, attacker_baseline, sign):
    """Vector-friendly form for recorded role signs in learner ingestion."""
    return sign * (attacker_return - attacker_baseline)


def sha256_file(path: str | os.PathLike) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class CheckpointRef:
    """A checkpoint path plus the bytes actors are authorized to load."""

    path: str
    sha256: str

    @classmethod
    def capture(cls, path: str | os.PathLike) -> "CheckpointRef":
        resolved = Path(path).resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"checkpoint unavailable: {resolved}")
        return cls(str(resolved), sha256_file(resolved))

    def verify(self) -> None:
        actual = sha256_file(self.path)
        if actual != self.sha256:
            raise RuntimeError(
                f"checkpoint digest drift for {self.path}: {actual}, "
                f"expected {self.sha256}")

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256}


def save_immutable_snapshot(net, directory: str | os.PathLike, *,
                            label: str, sequence: int) -> CheckpointRef:
    """Atomically publish one never-overwritten torch actor snapshot.

    The persistent fixed lock is an exclusive sequence owner.  The final uses
    a hard link rather than replacement, so a coordinator that lost a race can
    never overwrite the winner's supposedly immutable bytes.
    """
    import torch

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    stem = f"{label}_{sequence:06d}"
    lock = root / f".{stem}.lock"
    partial = root / f".{stem}.partial"
    existing = sorted(root.glob(f"{stem}_*.pt"))
    if existing:
        raise FileExistsError(
            f"refusing reused snapshot sequence {stem}: {existing}")
    try:
        with lock.open("xb") as fh:
            fh.write(b"shengji-immutable-snapshot-owner-v1\n")
            fh.flush()
            os.fsync(fh.fileno())
    except FileExistsError as exc:
        raise FileExistsError(
            f"refusing stale or concurrently owned snapshot sequence "
            f"{lock}") from exc
    try:
        with partial.open("xb") as fh:
            torch.save(net.state_dict(), fh)
            fh.flush()
            os.fsync(fh.fileno())
    except FileExistsError as exc:
        raise FileExistsError(
            f"refusing stale or concurrently owned snapshot partial "
            f"{partial}") from exc
    try:
        digest = sha256_file(partial)
        final = root / f"{stem}_{digest[:12]}.pt"
        if final.exists():
            raise FileExistsError(f"refusing to overwrite actor snapshot {final}")
        try:
            os.link(partial, final)
        except FileExistsError as exc:
            raise FileExistsError(
                f"refusing to overwrite actor snapshot {final}") from exc
        partial.unlink()
    except BaseException:
        # Leave the partial in place as a loud failed publication marker.  A
        # later run must choose a new directory or explicitly investigate it.
        raise
    ref = CheckpointRef(str(final.resolve()), digest)
    ref.verify()
    return ref


def load_verified(ref: CheckpointRef, loader):
    """Verify both sides of a load so a concurrent mutation cannot sneak in."""
    ref.verify()
    value = loader(ref.path)
    ref.verify()
    return value


def derive_job_seed(*, experiment: str, root_seed: int, purpose: str,
                    sequence: int, actor_sha256: str) -> int:
    """Named replay seed independent of wall clock and worker scheduling."""
    payload = (
        f"{experiment}|{int(root_seed)}|{purpose}|{int(sequence)}|"
        f"{actor_sha256}"
    ).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
