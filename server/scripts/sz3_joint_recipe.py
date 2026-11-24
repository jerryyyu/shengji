"""Emit SZ3 trainer commands and gate the large model's continuation."""
import argparse
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import sys

from sz2_joint_segment import RECIPE, RECIPE_SHA, joint_args

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BOUNDARY = 400
DEVICE = "mps"
ARCHITECTURE = {
    depth: f"d={48 * depth},heads={depth},enc_layers={depth},xattn_layers={depth},x_hidden=256"
    for depth in (6, 8)
}


class FailOffline(ValueError):
    pass


def _train_args(phase, root, recipe):
    smoke = phase == "L-smoke"
    depth = 6 if phase == "M" else 8
    directory = "L" if phase in ("L-prefix", "L-finish") else phase
    args = joint_args(recipe, ["--scratch-arch", ARCHITECTURE[depth]], root / directory / "train", DEVICE,
                      None if smoke else BOUNDARY, phase == "L-prefix")
    args.extend(["--microbatch-rounds", "4"])
    if smoke:
        args.extend(["--max-train-rows", "120000", "--capacity-stats"])
    return args


def smoke_result(directory):
    """Read the trainer's completed capacity measurement and final calibration."""
    lines = (directory / "status.log").read_text().splitlines()
    best = directory / "best.pt"
    if not lines or not re.fullmatch(rf"\S+ UTR DONE best={re.escape(str(best))} sha256=[0-9a-f]{{64}}", lines[-1]):
        raise ValueError("large smoke has no successful trainer terminal")
    if not all(path.is_file() and path.stat().st_size for path in (best, directory / "checkpoint.pt")):
        raise ValueError("large smoke did not save the best and resumable checkpoints")
    sample, = [json.loads(line.split(" CAPACITY ", 1)[1]) for line in lines if " CAPACITY " in line]
    for field in ("rows", "steps", "post_step_max_tensor_bytes", "post_step_max_driver_bytes"):
        if type(sample.get(field)) is not int or sample[field] <= 0:
            raise ValueError(f"large smoke lacks a positive {field}")
    for field in ("train_seconds", "rows_per_second"):
        if not math.isfinite(sample[field]) or sample[field] <= 0:
            raise ValueError(f"large smoke lacks a finite positive {field}")
    start, = [line for line in lines if " UTR START " in line]
    selected = re.search(r" rows=([1-9][0-9]*) ", start)
    if not selected or sample["epoch"] != 1 or sample["rows"] != int(selected[1]):
        raise ValueError("large smoke did not cover its selected rows")
    epoch, = [line for line in lines if " EPOCH 1 train " in line]
    calibration = epoch.split(" calib ", 1)[1]
    calib, end = json.JSONDecoder().raw_decode(calibration)
    if not calibration[end:].startswith(f" steps={sample['steps']} ") or not all(
            math.isfinite(calib[name]) for name in ("belief_ll", "leaf_value_end", "policy")):
        raise ValueError("large smoke calibration or optimizer progress is invalid")
    return dict(capacity=sample, calibration=calib)


def _large_can_resume(status, device):
    start = re.match(r"\S+ UTR START .* buffers=([1-9][0-9]*) init=scratch:", status[0])
    if not start or int(start[1]) <= BOUNDARY:
        return False
    buffers = int(start[1])
    pause = rf"\S+ UTR PAUSED at epoch 1 buffer {BOUNDARY}/{buffers} \(report boundary\); checkpoint saved"
    checkpoints = [index for index, line in enumerate(status) if re.fullmatch(pause, line)]
    if not checkpoints:
        return False

    device_suffix = "" if device == "cpu" else f" device={re.escape(device)}"
    stop = rf"\S+ STOPPED at epoch 1 buffer ([1-9][0-9]*)/{buffers} \(STOP file or --max-seconds\); checkpoint saved"
    buffer = BOUNDARY
    after_pause = status[checkpoints[-1] + 1:]
    if after_pause and not re.fullmatch(stop, after_pause[-1]):
        return False
    resuming = False
    for line in after_pause:
        if not resuming and re.fullmatch(rf"\S+ RESUME epoch 0 buffer {buffer}{device_suffix}", line):
            resuming = True
            continue
        stopped = re.fullmatch(stop, line)
        if resuming and stopped and buffer < int(stopped[1]) < buffers:
            buffer = int(stopped[1])
            resuming = False
            continue
        if resuming and re.match(r"\S+ epoch 1 buffer ", line):
            continue
        if not resuming and device == "mps" and re.match(r"\S+ DEVICE mps with PYTORCH_ENABLE_MPS_FALLBACK=1:", line):
            continue
        return False
    return not resuming


def _prefix(directory, expected, arch, *, paused):
    if json.loads((directory / "run.json").read_text()) != expected:
        raise ValueError(f"{directory}: trainer settings differ from the matched scratch recipe")
    status = (directory / "status.log").read_text().splitlines()
    starts = [index for index, line in enumerate(status) if " UTR START " in line]
    if len(starts) != 1 or " init=scratch:" not in status[starts[0]]:
        raise ValueError(f"{directory}: expected one scratch trainer start")
    status = status[starts[0]:]
    actual_arch, _ = json.JSONDecoder().raw_decode(status[0].split(" init=scratch:", 1)[1])
    if actual_arch != arch:
        raise ValueError(f"{directory}: trainer started a different architecture")
    if paused:
        checkpoint = directory / "checkpoint.pt"
        can_continue = _large_can_resume(status, expected.get("device", "cpu"))
    else:
        checkpoint = directory / "best.pt"
        terminal = rf"\S+ UTR DONE best={re.escape(str(checkpoint))} sha256=[0-9a-f]{{64}}"
        can_continue = re.fullmatch(terminal, status[-1])
    if not can_continue or not checkpoint.is_file():
        raise ValueError(f"{directory}: expected trainer terminal and checkpoint")
    report = json.loads((directory / f"epoch-1-buffer-{BOUNDARY}.json").read_text(), parse_float=Decimal)
    if not all(type(report[k]) is int and report[k] == wanted
               for k, wanted in (("epoch", 1), ("completed_buffers", BOUNDARY))):
        raise ValueError(f"{directory}: report covers a different prefix")
    counts = (report["rows"], report["leaves"])
    if any(type(n) is not int or n <= 0 for n in counts):
        raise ValueError(f"{directory}: expected positive row and leaf counts")
    losses = tuple(report["train"][metric] for metric in ("leaf_value", "policy"))
    if any(type(loss) not in (int, Decimal) or not Decimal(loss).is_finite() or loss < 0 for loss in losses):
        raise ValueError(f"{directory}: invalid prefix loss")
    return counts, losses


def prefix_decision(root, recipe):
    """Check the matched trainer artifacts before comparing the cumulative loss."""
    from shengji.train import unified_readout as trainer

    parser = trainer.build_parser()

    def prefix(phase):
        args = parser.parse_args(_train_args(phase, root, recipe))
        arch = dict(trainer.bs.DEFAULT_ARCH)
        arch.update((key, int(value)) for key, value in
                    (word.split("=") for word in args.scratch_arch.split(",")))
        return _prefix(Path(args.out), trainer._run_identity(args), arch, paused=args.pause_at_report)

    m_counts, medium = prefix("M")
    l_counts, large = prefix("L-prefix")
    if m_counts != l_counts:
        raise ValueError("the scratch prefix row or leaf counts differ")
    leaf, policy = (m - l for m, l in zip(medium, large))
    proceed = leaf >= Decimal("0.002") or policy >= Decimal("0.015")
    return proceed, (f"buffer={BOUNDARY} rows={m_counts[0]} leaves={m_counts[1]} "
                     f"leaf_value_M_minus_L={leaf} policy_M_minus_L={policy}")


def command(phase, root, recipe_path):
    raw = recipe_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RECIPE_SHA:
        raise ValueError("FT-500k recipe SHA mismatch")
    recipe = json.loads(raw)
    if phase == "L-finish":
        stop = root / "L/train/STOP"
        if stop.exists() or stop.is_symlink():
            raise ValueError("operator STOP present on the large arm")
        proceed, detail = prefix_decision(root, recipe)
        if not proceed:
            raise FailOffline(detail)
        print(f"CONTINUE {detail}", file=sys.stderr)
    return [sys.executable, "-B", "-m", "shengji.train.unified_readout", *_train_args(phase, root, recipe)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("L-smoke", "M", "L-prefix", "L-finish"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--recipe", type=Path, default=RECIPE)
    args = parser.parse_args(argv)
    try:
        argv = command(args.phase, args.root.resolve(), args.recipe)
    except FailOffline as exc:
        parser.exit(8, f"FAIL-OFFLINE {exc}\n")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"invalid recipe: {exc}\n")
    print(json.dumps(argv))


if __name__ == "__main__":
    main()
