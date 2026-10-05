"""Explicit single-row Sol/PT-Sol adapter; dry-run unless --run is supplied.

Does not grant launch authority or implement campaign reservation, RELEASE,
HOLD, memory admission, retries of rows, or scientific readout.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.w32_llm_benchmark import parse_seeds, run_benchmark
from shengji.luna.benchmark_failure_protocol import FAIL_STOP, PRESERVE_ILLEGAL
from shengji.luna.benchmark_recipes import prepare_recipe


def run_row(*, row, model_paths, prepared_roots_from, prepared_roots_sha256,
            output, seeds, run=False, codex_binary="codex", capacity_retries=False,
            accept_recovered_reconnects=False, invalid_action_feedback=False,
            classify_final_action_failures=False, failure_protocol=FAIL_STOP,
            retention_plan=None, retention_plan_sha256=None):
    controls = dict(capacity_retries=capacity_retries,
                    accept_recovered_reconnects=accept_recovered_reconnects,
                    invalid_action_feedback=invalid_action_feedback,
                    classify_final_action_failures=classify_final_action_failures)
    if type(run) is not bool or any(type(v) is not bool for v in controls.values()):
        raise ValueError("run and recovery controls must be bool")
    if failure_protocol not in (FAIL_STOP, PRESERVE_ILLEGAL):
        raise ValueError("unknown failure protocol")
    if failure_protocol == PRESERVE_ILLEGAL and not classify_final_action_failures:
        raise ValueError("preserve protocol requires final-action attribution")
    if (retention_plan is None) != (retention_plan_sha256 is None):
        raise ValueError("retention requires plan and SHA together")
    if retention_plan is not None and (failure_protocol != PRESERVE_ILLEGAL or row != "m1-prior"):
        raise ValueError("panel retention requires amended M1 row")
    if prepared_roots_from is None or prepared_roots_sha256 is None:
        raise ValueError("panel requires shared pinned roots")
    recipe = prepare_recipe(row, model_paths)
    options = {name: value for name, value in controls.items() if value}
    if failure_protocol == PRESERVE_ILLEGAL:
        options.update(failure_protocol=failure_protocol, illegal_failure_limit=8)
    if retention_plan is not None:
        options.update(retention_plan=retention_plan, retention_plan_sha256=retention_plan_sha256)
    return run_benchmark(
        checkpoint=recipe.identity.get("checkpoint"), policy=recipe.policy,
        prepared_recipe=recipe, prepared_roots_from=prepared_roots_from,
        prepared_roots_sha256=prepared_roots_sha256, output=output, seeds=seeds,
        models=("sol",), information=("actor-only", "perfect"),
        wall_seconds=43200.0, token_limit=45000000, timeout_seconds=300,
        run=run, codex_binary=codex_binary, **options)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--row", required=True)
    parser.add_argument("--model-assets", type=Path)
    parser.add_argument("--prepared-roots-from", required=True)
    parser.add_argument("--prepared-roots-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seeds", nargs="+", required=True)
    parser.add_argument("--codex-binary", default="codex")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--retry-provider-capacity", dest="capacity_retries", action="store_true")
    parser.add_argument("--accept-recovered-reconnects", action="store_true")
    parser.add_argument("--invalid-action-feedback", action="store_true")
    parser.add_argument("--classify-final-action-failures", action="store_true")
    parser.add_argument("--failure-protocol", choices=(FAIL_STOP, PRESERVE_ILLEGAL), default=FAIL_STOP)
    parser.add_argument("--retention-plan")
    parser.add_argument("--retention-plan-sha256")
    args = vars(parser.parse_args(argv))
    try:
        assets = args.pop("model_assets")
        paths = {} if assets is None else json.loads(assets.read_text())
        if not isinstance(paths, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                              for k, v in paths.items()):
            raise ValueError("model assets must map string keys to paths")
        args["seeds"] = parse_seeds(args["seeds"])
        result = run_row(model_paths=paths, **args)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
