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
SMOKE_BOUNDARY = 1
DEVICE = "mps"
SCRATCH_RATES = dict(lr=3e-4, head_lr=1e-3, readout_lr=1e-3)
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
    args = joint_args({**recipe, **SCRATCH_RATES}, ["--scratch-arch", ARCHITECTURE[depth]], root / directory / "train", DEVICE,
                      SMOKE_BOUNDARY if smoke else BOUNDARY, phase == "L-prefix")
    args.extend(["--microbatch-rounds", "4"])
    if smoke:
        args.extend(["--max-train-rows", "120000", "--capacity-stats"])
    return args


def smoke_result(directory):
    """Read both completed training legs and the final calibration."""
    lines = (directory / "status.log").read_text().splitlines()
    best = directory / "best.pt"
    if not lines or not re.fullmatch(rf"\S+ UTR DONE best={re.escape(str(best))} sha256=[0-9a-f]{{64}}", lines[-1]):
        raise ValueError("large smoke has no successful trainer terminal")
    if not all(path.is_file() and path.stat().st_size for path in (best, directory / "checkpoint.pt")):
        raise ValueError("large smoke did not save the best and resumable checkpoints")

    events = []
    for line in lines:
        event = re.fullmatch(r"\S+ (UTR START|CAPACITY|UTR PAUSED|RESUME|EPOCH|UTR DONE|UTR ABORT|STOPPED) (.*)", line)
        if event:
            events.append(event.groups())
    if [name for name, _ in events] != ["UTR START", "CAPACITY", "UTR PAUSED", "RESUME", "CAPACITY", "EPOCH", "UTR DONE"]:
        raise ValueError("large smoke lacks the split training terminals and two capacity samples")
    start, first, pause, resume, second, epoch, _ = (text for _, text in events)
    started = re.fullmatch(r".* rows=([1-9][0-9]*) chunks=[1-9][0-9]* buffers=([1-9][0-9]*) .* device=mps", start)
    if not started:
        raise ValueError("large smoke lacks the selected rows and buffer count")
    selected_rows, buffers = map(int, started.groups())
    if (buffers <= SMOKE_BOUNDARY or
            pause != f"at epoch 1 buffer {SMOKE_BOUNDARY}/{buffers} (report boundary); checkpoint saved" or
            resume != f"epoch 0 buffer {SMOKE_BOUNDARY} device=mps"):
        raise ValueError("large smoke paused or resumed at the wrong buffer")

    samples = [json.loads(first), json.loads(second)]
    memory_fields = ("post_step_max_tensor_bytes", "post_step_max_driver_bytes")
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError("large smoke capacity sample is not a JSON object")
        for field in ("rows", "steps", *memory_fields):
            if type(sample.get(field)) is not int or sample[field] <= 0:
                raise ValueError(f"large smoke lacks a positive {field}")
        for field in ("train_seconds", "rows_per_second"):
            if type(sample.get(field)) not in (int, float) or not math.isfinite(sample[field]) or sample[field] <= 0:
                raise ValueError(f"large smoke lacks a finite positive {field}")
        if (type(sample.get("epoch")) is not int or sample["epoch"] != 1 or sample["steps"] > sample["rows"] or
                sample["post_step_max_driver_bytes"] < sample["post_step_max_tensor_bytes"] or
                not math.isclose(sample["rows_per_second"], sample["rows"] / sample["train_seconds"])):
            raise ValueError("large smoke has an inconsistent capacity sample")

    report = json.loads((directory / f"epoch-1-buffer-{SMOKE_BOUNDARY}.json").read_text())
    prefix = dict(epoch=1, completed_buffers=SMOKE_BOUNDARY, rows=samples[0]["rows"], steps=samples[0]["steps"])
    if (not isinstance(report, dict) or
            any(type(report.get(field)) is not int or report[field] != expected for field, expected in prefix.items()) or
            type(report.get("leaves")) is not int or report["leaves"] <= 0):
        raise ValueError("large smoke prefix report does not match its capacity sample")

    rows = sum(sample["rows"] for sample in samples)
    train_seconds = sum(sample["train_seconds"] for sample in samples)
    if rows != selected_rows or not math.isfinite(train_seconds):
        raise ValueError("large smoke did not cover its selected rows")
    epoch_parts = epoch.split(" calib ", 1)
    if len(epoch_parts) != 2 or not epoch_parts[0].startswith("1 train "):
        raise ValueError("large smoke has no first-epoch calibration")
    calibration = epoch_parts[1]
    calib, end = json.JSONDecoder().raw_decode(calibration)
    if (not isinstance(calib, dict) or not re.fullmatch(rf" steps={samples[1]['steps']} \(\d+s\)", calibration[end:]) or
            not all(type(calib.get(name)) in (int, float) and math.isfinite(calib[name])
                    for name in ("belief_ll", "leaf_value_end", "policy"))):
        raise ValueError("large smoke calibration or optimizer progress is invalid")
    capacity = dict(epoch=1, rows=rows, steps=sum(sample["steps"] for sample in samples),
                    train_seconds=train_seconds, rows_per_second=rows / train_seconds)
    capacity.update((field, max(sample[field] for sample in samples)) for field in memory_fields)
    return dict(capacity=capacity, calibration=calib)


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


def arm_prefix(phase, root, recipe):
    from shengji.train import unified_readout as trainer

    args = trainer.build_parser().parse_args(_train_args(phase, root, recipe))
    arch = dict(trainer.bs.DEFAULT_ARCH)
    arch.update((key, int(value)) for key, value in
                (word.split("=") for word in args.scratch_arch.split(",")))
    return _prefix(Path(args.out), trainer._run_identity(args), arch, paused=args.pause_at_report)


def prefix_decision(root, recipe):
    """Check the matched trainer artifacts before comparing the cumulative loss."""
    m_counts, medium = arm_prefix("M", root, recipe)
    l_counts, large = arm_prefix("L-prefix", root, recipe)
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
    args = _train_args(phase, root, recipe)
    directory = Path(args[args.index("--out") + 1])
    if directory.is_symlink() or directory.parent.is_symlink():
        raise ValueError("arm output must be inside its reserved root")
    if phase != "L-smoke":
        stop = directory / "STOP"
        if stop.exists() or stop.is_symlink():
            raise ValueError("operator STOP present on the arm")
    if phase == "L-finish":
        proceed, detail = prefix_decision(root, recipe)
        if not proceed:
            raise FailOffline(detail)
        print(f"CONTINUE {detail}", file=sys.stderr)
    if directory.exists() and phase != "L-smoke":
        status = (directory / "status.log").read_text().splitlines()
        terminal = re.fullmatch(
            r"\S+ (STOPPED|UTR PAUSED) at epoch 1 buffer ([1-9][0-9]*)/([1-9][0-9]*) "
            r"\((STOP file or --max-seconds|report boundary)\); checkpoint saved", status[-1] if status else "",
        )
        if (not terminal or int(terminal[2]) >= int(terminal[3]) or not (directory / "checkpoint.pt").is_file()
                or (terminal[1], terminal[4]) not in {("STOPPED", "STOP file or --max-seconds"),
                                                       ("UTR PAUSED", "report boundary")}
                or (terminal[1] == "UTR PAUSED" and phase != "L-finish")
                or (phase == "L-prefix" and int(terminal[2]) >= BOUNDARY)):
            raise ValueError("expected a clean checkpointed segment before resuming")
        args.extend(["--expect-resume-buffer", terminal[2]])
    return [sys.executable, "-B", "-m", "shengji.train.unified_readout", *args]


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
