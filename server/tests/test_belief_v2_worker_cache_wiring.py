"""Production-worker witnesses for deferred exact tensor-cache verification."""

import ast
from pathlib import Path


def test_device_and_training_workers_defer_full_sweep_at_exact_call_sites():
    path = Path(__file__).parents[1] / "scripts" / "belief_v2_worker.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = {
        node.name: node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for name in ("qualify_device", "train_cohort"):
        calls = [
            node for node in ast.walk(functions[name])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "reopen_training_tensor_cache"]
        assert len(calls) == 1
        keywords = {row.arg: row.value for row in calls[0].keywords}
        assert isinstance(keywords.get("verify_all_bytes"), ast.Constant)
        assert keywords["verify_all_bytes"].value is False
