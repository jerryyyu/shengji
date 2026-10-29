"""The served configuration comes from fly.toml (`shengji.eval.served_config`), and no harness keeps its own copy.

Package-free: the registry names are derived with the package hashes taken from the env's own pins (the
hashing is stubbed), so every check here runs without the model files.

- `served_env` is fly.toml's [env] exactly, with mapped volume paths and named overrides only;
- each named override touches exactly the keys it declares, builds a valid recipe, and an unknown name refuses;
- fly.toml's SHENGJI_BOT is the name its own recipe registers, and an override re-derives it;
- every harness entry point that claims the served bot returns fly.toml's env up to its named overrides
  (`SERVED_HARNESSES`);
- no module under shengji/ or scripts/ hand-sets a play recipe (a literal with SHENGJI_PV_WORLDS /
  _CANDIDATES / _CAP) except the named historical baselines in `HISTORICAL_RECIPES`.
"""
import ast
from pathlib import Path

import pytest

from shengji.eval import served_config as sc

SERVER = Path(__file__).resolve().parents[1]
FLY = sc.fly_env()
MAP = {FLY["SHENGJI_PV_CKPT"]: "/local/pv.npz", FLY["SHENGJI_PV_BELIEF_CKPT"]: "/local/belief.npz"}

#: hand-set recipes that are deliberately NOT the served bot: each a fixed historical baseline, named by its
#: release, that recorded evidence is bound to.  (file, assigned or enclosing name) -> why it stays.
HISTORICAL_RECIPES = {
    ("shengji/eval/tactical.py", "RELEASE36_PLAY_ENV"):
        "the release-36 baseline the recorded fixture verdicts and the frozen r36-SMV3 observation control use",
    ("scripts/qualify_exact_lead.py", "qualification_env"):
        "the release 44 / 45 exact-lead qualification recipes, bound to their recorded baselines",
}


@pytest.fixture
def pinned_hashes(monkeypatch):
    """Package hashes from the env's own pins: a name derives without the files."""
    import shengji.ai.cwv_policy as cwv
    from shengji.train import pv_search_policy as pv
    pins = {"/local/pv.npz": FLY["SHENGJI_PV_SHA256"], FLY["SHENGJI_PV_CKPT"]: FLY["SHENGJI_PV_SHA256"],
            "/local/belief.npz": FLY["SHENGJI_PV_BELIEF_SHA256"],
            FLY["SHENGJI_PV_BELIEF_CKPT"]: FLY["SHENGJI_PV_BELIEF_SHA256"]}
    monkeypatch.setattr(cwv, "checkpoint_id", lambda path: pins[str(path)][:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: pins[str(path)])


def test_served_env_is_fly_toml_with_mapped_paths():
    assert sc.served_env() == FLY
    env = sc.served_env(mappings=MAP)
    assert sc.env_diff(env, FLY) == sorted({"SHENGJI_PV_CKPT", "SHENGJI_PV_BELIEF_CKPT"})
    assert env["SHENGJI_PV_CKPT"] == "/local/pv.npz"
    assert sc.unexplained_diff(env, mappings=MAP) == []


def test_named_overrides_touch_only_their_keys():
    for name, keys in sc.NAMED_OVERRIDES.items():
        assert keys and all(k.startswith("SHENGJI_PV_") for k in keys), name
        changed = set(sc.env_diff(sc.apply_overrides(FLY, [name]), FLY))
        assert changed <= set(keys), (name, changed)
        assert changed, f"{name} changes nothing in fly.toml"
    with pytest.raises(sc.ServedConfigError, match="unknown override"):
        sc.apply_overrides(FLY, ["wla-not-a-knob"])
    with pytest.raises(sc.ServedConfigError, match="unknown override"):
        sc.override_keys(["wla-not-a-knob"])


def test_fly_toml_name_is_its_recipe_and_overrides_rederive_it(pinned_hashes):
    assert sc.registry_name(sc.served_env(mappings=MAP)) == FLY["SHENGJI_BOT"]
    seen = {FLY["SHENGJI_BOT"]}
    for name in sc.NAMED_OVERRIDES:
        env = sc.served_env(mappings=MAP, overrides=[name])
        assert env["SHENGJI_BOT"] == sc.registry_name(env) and env["SHENGJI_BOT"] not in seen, name
        seen.add(env["SHENGJI_BOT"])
        assert sc.unexplained_diff(env, mappings=MAP, overrides=[name]) == []


def test_teacher_override_unbudgets_the_recipe(pinned_hashes):
    from shengji.train.pv_search_policy import pv_env_recipe
    served = pv_env_recipe(sc.served_env(mappings=MAP))
    teacher = pv_env_recipe(sc.served_env(mappings=MAP, overrides=["teacher-unbudgeted"]))
    assert served["serving_budget_seconds"] and served["leaf_greedy_deadline_ms"]
    for key in ("serving_budget_seconds", "bury_serving_budget_seconds", "leaf_greedy_deadline_ms"):
        assert not teacher.get(key), key   # absent: the recipe default, off


def test_unexplained_diff_names_a_hand_change():
    env = {**sc.served_env(mappings=MAP), "SHENGJI_PV_CANDIDATES": "16"}
    assert sc.unexplained_diff(env, mappings=MAP) == ["SHENGJI_PV_CANDIDATES"]
    env = sc.served_env(mappings=MAP)
    env.pop("SHENGJI_PV_ENCODE_NATIVE")
    assert sc.unexplained_diff(env, mappings=MAP) == ["SHENGJI_PV_ENCODE_NATIVE"]


def _tactical(overrides):
    from shengji.eval import tactical
    return tactical.served_environ(MAP, overrides=overrides)


def _smoke(overrides):
    assert not overrides
    import sys
    sys.path.insert(0, str(SERVER))
    from scripts.cwv_serving_smoke import env_from_fly_toml
    return env_from_fly_toml(sc.FLY_TOML, MAP)


#: every entry point that claims the served bot: label -> env builder(overrides)
SERVED_HARNESSES = {"tactical.served_environ": _tactical, "cwv_serving_smoke.env_from_fly_toml": _smoke}


@pytest.mark.parametrize("label", sorted(SERVED_HARNESSES))
def test_every_served_harness_is_fly_toml(label, pinned_hashes):
    cases = [()] if label.startswith("cwv_serving_smoke") else [()] + [(n,) for n in sc.NAMED_OVERRIDES]
    for overrides in cases:
        env = SERVED_HARNESSES[label](overrides)
        assert sc.unexplained_diff(env, mappings=MAP, overrides=overrides) == [], (label, overrides)


def _hand_set_recipes(root=SERVER):
    """(file, name) of every literal that sets a play recipe: a dict display or dict(...) call with
    SHENGJI_PV_WORLDS, _CANDIDATES or _CAP among its keys; name = the enclosing function or class, else the
    module-level name assigned."""
    recipe_keys = {"SHENGJI_PV_WORLDS", "SHENGJI_PV_CANDIDATES", "SHENGJI_PV_CAP"}
    found = set()
    files = sorted((root / "shengji").rglob("*.py")) + sorted((root / "scripts").glob("*.py"))
    for path in files:
        tree = ast.parse(path.read_text())
        rel = str(path.relative_to(root))

        def visit(node, owner):
            for child in ast.iter_child_nodes(node):
                name = owner
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = child.name
                elif (owner == "<module>" and isinstance(child, ast.Assign) and len(child.targets) == 1
                      and isinstance(child.targets[0], ast.Name)):
                    name = child.targets[0].id
                keys = set()
                if isinstance(child, ast.Dict):
                    keys = {k.value for k in child.keys if isinstance(k, ast.Constant)}
                elif isinstance(child, ast.Call) and getattr(child.func, "id", None) == "dict":
                    keys = {k.arg for k in child.keywords}
                if keys & recipe_keys:
                    found.add((rel, owner))
                visit(child, name)
        visit(tree, "<module>")
    return found


def test_no_harness_hand_sets_the_served_recipe():
    found = _hand_set_recipes()
    assert found == set(HISTORICAL_RECIPES), (
        "a hand-set play recipe: build the served bot from fly.toml (shengji.eval.served_config) or, for a "
        f"fixed historical baseline, name it by its release and list it in HISTORICAL_RECIPES: {sorted(found)}")


def test_the_scan_finds_a_hand_set_recipe(tmp_path):
    (tmp_path / "shengji").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "shengji" / "a.py").write_text('SERVED_ENV = {"SHENGJI_PV_WORLDS": "64", "SHENGJI_PV_CANDIDATES": "8"}\n')
    (tmp_path / "scripts" / "b.py").write_text('def production():\n    return dict(SHENGJI_PV_CAP="4000")\n')
    (tmp_path / "scripts" / "c.py").write_text('ENV = {"SHENGJI_PV_LEAD_CONFIRM": "32"}\n')
    assert _hand_set_recipes(tmp_path) == {("shengji/a.py", "SERVED_ENV"), ("scripts/b.py", "production")}


@pytest.mark.parametrize('overrides', [[], ['teacher-unbudgeted']])
def test_shell_export_replaces_inherited_recipe(overrides, pinned_hashes, capsys):
    import json
    import os
    import shlex
    import subprocess
    import sys
    from shengji.train.pv_search_policy import pv_env_recipe

    args = ['env']
    for src, dst in MAP.items():
        args += ['--map', f'{src}={dst}']
    for override in overrides:
        args += ['--override', override]
    assert sc.main(args) == 0
    script = capsys.readouterr().out
    inherited = dict(os.environ, SHENGJI_PV_SERVING_BUDGET_SECONDS='3',
                     SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS='2',
                     SHENGJI_PV_LEAF_GREEDY_DEADLINE='2',
                     SHENGJI_PV_LEAD_CONFIRM='32', KEEP_UNRELATED='present')
    probe = shlex.join([sys.executable, '-c',
                       'import os,json; print(json.dumps(dict(os.environ)))'])
    result = subprocess.run(['/bin/sh', '-c', script + '\n' + probe], env=inherited,
                            text=True, capture_output=True, check=True)
    actual = json.loads(result.stdout)
    expected = sc.served_env(mappings=MAP, overrides=overrides)
    assert pv_env_recipe(actual) == pv_env_recipe(expected)
    assert actual['SHENGJI_BOT'] == sc.registry_name(actual)
    assert actual['KEEP_UNRELATED'] == 'present'


def test_builder_refuses_previous_registration(monkeypatch, pinned_hashes):
    from shengji.ai import registry
    from shengji.train import pv_search_policy as pv
    from shengji.train import cwv_bury_policy, cwv_shortlist

    monkeypatch.setattr(cwv_bury_policy, 'bury_env_recipe', lambda env: None)
    monkeypatch.setattr(cwv_shortlist, 'shortlist_env_recipe', lambda env: None)
    monkeypatch.setattr(registry, 'REGISTRY', {})
    built = []

    def register(checkpoint, **recipe):
        entries = pv.pv_registry_entries(checkpoint, **recipe)
        registry.REGISTRY.update(entries)
        return sorted(entries)

    def make(name, seed):
        built.append(name)
        return name

    monkeypatch.setattr(registry, 'register_pv_search_policies', register)
    monkeypatch.setattr(registry, 'make_bot', make)
    base = sc.served_env(mappings=MAP)
    sc.build_served_bot(base)
    changed = {**base, 'SHENGJI_PV_CANDIDATES': '9'}
    with pytest.raises(sc.ServedConfigError, match='not registered by this env'):
        sc.build_served_bot(changed)
    assert built == [base['SHENGJI_BOT']]
    changed['SHENGJI_BOT'] = sc.registry_name(changed)
    assert sc.build_served_bot(changed)[0] == changed['SHENGJI_BOT']
