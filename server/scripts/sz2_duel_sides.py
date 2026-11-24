"""Build the registered sides for the paired SZ2 comparisons without dealing a round."""
import hashlib
import json
from pathlib import Path
import os
import subprocess
import sys


FLEET = Path.home() / "fleet"
REFERENCE = FLEET / "claude-ft500/recipe.h2h.json"
REFERENCE_SHA = "8b17f894f6e94cf3e40c33c64ed2441d7ef8a9ffe0f6dea35facf3dfb020bc14"


def side_words(template, package):
    path, digest, belief, belief_sha = package
    replacements = {"UT_SIDE_PKG": path, "UT_SIDE_SHA256": digest,
                    "SHENGJI_PV_BELIEF_CKPT": belief, "SHENGJI_PV_BELIEF_SHA256": belief_sha}
    words = []
    for word in template:
        key, value = word.split("=", 1)
        words.append(f"{key}={replacements.pop(key, value)}")
    if replacements or any("," in word for word in words):
        raise ValueError("incomplete or unrepresentable duel side")
    return words


def load_reference():
    data = REFERENCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != REFERENCE_SHA:
        raise ValueError("reference duel recipe changed")
    return json.loads(data)


def build_sides(packages):
    return build_sides_from_reference(packages, load_reference())


def build_sides_from_reference(packages, reference):
    tree = Path(reference["tree"])
    for command, expected in ((["rev-parse", "HEAD"], reference["tree_head"]), (["status", "--porcelain"], "")):
        actual = subprocess.check_output(["git", "-C", tree, *command], text=True).strip()
        if actual != expected:
            raise ValueError("duel source tree differs from the reference")
    kit = REFERENCE.parent / "kit"
    for name, digest in reference["pins"].items():
        path = Path(name)
        if path.parent == kit or tree in path.parents:
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise ValueError(f"duel dependency changed: {path.name}")

    labels = ("S", "M", "FT500")
    if len({packages[label][1] for label in labels}) != 3:
        raise ValueError("duel challengers and controls must have distinct readouts")
    template = reference["arms"]["FXR"]["exploiter_words"]
    words = {label: side_words(template, packages[label]) for label in labels}
    inputs = FLEET / "claude-ut-inside1/inputs"
    env = {"HOME": str(Path.home()), "PATH": os.defpath, "PYTHONPATH": str(tree / "server"),
           "SHENGJI_FAST": "1", "FIND_GAPS_SERVER": str(tree / "server"),
           "FIND_GAPS_PKG": str(inputs / "g3a-e04-f4f4127e.npz"),
           "FIND_GAPS_PATH_MAP": ";".join(f"/data/models/{name}={inputs / name}"
                                          for name in ("b1a-028131a0.npz", "p0-ft1-1fa201b2.npz"))}
    for threads in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[threads] = "1"
    result = subprocess.run([sys.executable, "-B", kit / "probe_names.ut.py", kit / "ut_h2h_adapter.py",
                             *[",".join(words[label]) for label in labels]], env=env, cwd=tree / "server",
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise ValueError(f"duel bot construction failed: {result.stderr[-1500:]}")
    names = dict(zip(labels, json.loads(result.stdout.splitlines()[-1]), strict=True))
    for label, name in names.items():
        short = packages[label][1][:8]
        if not name.endswith(f"-sc8-ushare{short}-uvalue{short}-ureply{short}"):
            raise ValueError(f"{label} did not bind all three unified slots")
    if names["FT500"] != reference["arms"]["FXR"]["exploiter_name"]:
        raise ValueError("descriptive control differs from the reference bot")
    arms = {}
    for key, control, seed in (("SZ2-A", "S", 2665000000), ("SZ2-B", "FT500", 2665001000)):
        arm = {"seed0": seed, "deals": 1000}
        for tag, label, role in (("ex", "M", "exploiter"), ("def", control, "defender")):
            path, digest, belief, belief_sha = packages[label]
            arm.update({f"{tag}_package": path, f"{tag}_package_sha256": digest,
                        f"{tag}_belief": belief, f"{tag}_belief_sha256": belief_sha,
                        f"{role}_name": names[label], f"{role}_words": words[label]})
        arms[key] = arm
    return arms


if __name__ == "__main__":
    from sz2_duel_exports import verified_exports
    print(json.dumps(build_sides(verified_exports()), sort_keys=True))
