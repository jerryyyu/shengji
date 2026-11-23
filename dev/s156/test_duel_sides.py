import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server/scripts"))
import sz2_duel_sides as sides


def test_decision_and_descriptive_controls_reach_the_registered_slots(tmp_path, monkeypatch):
    tree = tmp_path / "tree"
    (tree / "server").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", tree], check=True)
    subprocess.run(["git", "-C", tree, "-c", "user.name=fixture", "-c", "user.email=test@localhost",
                    "commit", "--allow-empty", "-qm", "fixture"], check=True)
    head = subprocess.check_output(["git", "-C", tree, "rev-parse", "HEAD"], text=True).strip()
    kit = tmp_path / "kit"
    kit.mkdir()
    probe = kit / "probe_names.ut.py"
    probe.write_text("""import json, sys
names = []
for arg in sys.argv[2:]:
    env = dict(word.split('=', 1) for word in arg.split(','))
    label = env['UT_SIDE_PKG']
    assert env['SHENGJI_PV_BELIEF_CKPT'] == label + '-belief'
    assert env['UT_PRIOR'] == 'shared' and env['UT_VALUE'] == env['UT_REPLY'] == 'readout'
    h = env['UT_SIDE_SHA256'][:8]
    names.append('test-sc8-ushare' + h + '-uvalue' + h + '-ureply' + h)
print(json.dumps(names))
""")
    packages = {label: (label, c * 64, label + "-belief", "a" * 64)
                for label, c in (("S", "1"), ("M", "2"), ("FT500", "3"))}
    words = ["UT_SIDE_PKG=x", "UT_SIDE_SHA256=x", "SHENGJI_PV_BELIEF_CKPT=x", "SHENGJI_PV_BELIEF_SHA256=x",
             "UT_PRIOR=shared", "UT_VALUE=readout", "UT_REPLY=readout"]
    reference = tmp_path / "recipe.json"
    ref_name = "test-sc8-ushare33333333-uvalue33333333-ureply33333333"
    reference.write_text(json.dumps({"tree": str(tree), "tree_head": head,
                                     "pins": {str(probe): hashlib.sha256(probe.read_bytes()).hexdigest()},
                                     "arms": {"FXR": {"exploiter_words": words, "exploiter_name": ref_name}}}))
    monkeypatch.setattr(sides, "REFERENCE", reference)
    monkeypatch.setattr(sides, "REFERENCE_SHA", hashlib.sha256(reference.read_bytes()).hexdigest())
    arms = sides.build_sides(packages)
    for key, defender, seed in (("SZ2-A", "S", 2665000000), ("SZ2-B", "FT500", 2665001000)):
        arm = arms[key]
        assert (arm["seed0"], arm["deals"]) == (seed, 1000)
        assert arm["ex_package"] == "M" and arm["def_package"] == defender
        assert arm["defender_name"].endswith(packages[defender][1][:8])
        assert arm["exploiter_name"].endswith(packages["M"][1][:8])
    with pytest.raises(ValueError, match="distinct readouts"):
        sides.build_sides(dict(packages, S=packages["M"]))
    probe.write_text("raise SystemExit(0)")
    with pytest.raises(ValueError, match="dependency changed"):
        sides.build_sides(packages)
