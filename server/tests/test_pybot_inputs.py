"""The app's offline bot is never packaged from stale sources (``web/ios/pybot/inputs.sh``).

``build_payload.sh`` and ``build_fast_ext.sh`` record the inputs each built part
came from; the Xcode phase ``xcode_install_python.sh`` refuses, before it
copies anything into the app, a part whose inputs have changed since, and
prints the bundle's input digest when they have not.  These tests run the real
scripts on a small stand-in checkout: a changed ``.py``, ``.pyx`` or
``fly.toml`` is refused, an unchanged one is reused.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

PYBOT = Path(__file__).resolve().parents[2] / "web" / "ios" / "pybot"
SCRIPTS = ("inputs.sh", "xcode_install_python.sh", "build_fast_ext.sh", "offline_bot.py")
PYX = ("engine/_fast", "ai/_cwv_math", "ai/_endgame_fast", "train/_pv_fast")

pytestmark = pytest.mark.skipif(shutil.which("bash") is None or shutil.which("rsync") is None,
                                reason="needs bash and rsync")


@pytest.fixture
def tree(tmp_path):
    """A checkout with the pybot scripts, a tiny shengji package and fly.toml,
    a stand-in xcframework, and both parts recorded as built."""
    pkg = tmp_path / "server" / "shengji"
    for rel in ("__init__.py", "engine/round.py", "ai/smart.py"):
        (pkg / rel).parent.mkdir(parents=True, exist_ok=True)
        (pkg / rel).write_text(f"# {rel}\n")
    for rel in PYX:
        (pkg / f"{rel}.pyx").parent.mkdir(parents=True, exist_ok=True)
        (pkg / f"{rel}.pyx").write_text(f"# {rel}\n")
    (tmp_path / "fly.toml").write_text("[env]\nSHENGJI_BOT = 'x'\n")
    pybot = tmp_path / "web" / "ios" / "pybot"
    pybot.mkdir(parents=True)
    for name in SCRIPTS:
        shutil.copy2(PYBOT / name, pybot / name)
    xc = pybot / "Python.xcframework"
    (xc / "build").mkdir(parents=True)
    (xc / "Info.plist").write_text("<plist/>\n")
    for sl in ("ios-arm64", "ios-arm64_x86_64-simulator"):
        inc = xc / sl / "include" / "python3.14"
        inc.mkdir(parents=True)
        (inc / "patchlevel.h").write_text("#define PY_VERSION \"3.14.10\"\n")
        (inc / "pyconfig.h").write_text("\n")
    # the packaging helpers the phase sources (BeeWare's utils.sh), reduced to the layout
    (xc / "build" / "utils.sh").write_text(
        'install_stdlib() { mkdir -p "$CODESIGNING_FOLDER_PATH/python/lib/python3.14"; }\n'
        'process_dylibs() { :; }\n')
    for part in ("payload", "fast"):
        (pybot / part).mkdir()
        _run(pybot, "inputs.sh", "record", part, str(pybot / part))
    (pybot / "fast" / "iphonesimulator").mkdir()
    (pybot / "fast" / "iphonesimulator" / "ext.so").write_text("so\n")
    (pybot / "payload" / "fly.toml").write_text("[env]\n")
    (pybot / "site" / "iphonesimulator").mkdir(parents=True)
    (tmp_path / "web" / "ios" / "App").mkdir()
    return tmp_path


def _run(pybot: Path, script: str, *args, env=None):
    return subprocess.run(["bash", str(pybot / script), *args], capture_output=True, text=True,
                          env={**os.environ, **(env or {})})


def _check(tree: Path, part: str):
    pybot = tree / "web" / "ios" / "pybot"
    return _run(pybot, "inputs.sh", "check", part, str(pybot / part))


def _package(tree: Path):
    app = tree / "App.app"
    pybot = tree / "web" / "ios" / "pybot"
    return app, _run(pybot, "xcode_install_python.sh", env={
        "PROJECT_DIR": str(tree / "web" / "ios" / "App"), "EFFECTIVE_PLATFORM_NAME": "-iphonesimulator",
        "CODESIGNING_FOLDER_PATH": str(app)})


def test_unchanged_sources_are_reused_and_the_bundle_identity_printed(tree):
    assert _check(tree, "payload").returncode == 0
    assert _check(tree, "fast").returncode == 0
    app, out = _package(tree)
    assert out.returncode == 0, out.stdout + out.stderr
    line = next(ln for ln in out.stdout.splitlines() if ln.startswith("pybot bundle: inputs "))
    identity = line.split()[3]
    assert len(identity) == 64
    assert (app / "python" / "app" / "BUNDLE_INPUTS").read_text().strip() == identity
    assert (app / "python" / "app" / "offline_bot.py").exists()
    # the same inputs give the same identity
    _, again = _package(tree)
    assert line in again.stdout


@pytest.mark.parametrize("rel, part", [
    ("server/shengji/engine/round.py", "payload"),
    ("server/shengji/ai/new_module.py", "payload"),
    ("fly.toml", "payload"),
    ("server/shengji/engine/_fast.pyx", "fast"),
    ("web/ios/pybot/Python.xcframework/ios-arm64/include/python3.14/patchlevel.h", "fast"),
])
def test_a_changed_input_is_refused_before_packaging(tree, rel, part):
    path = tree / rel
    path.write_text((path.read_text() if path.exists() else "") + "# changed\n")
    other = {"payload": "fast", "fast": "payload"}[part]
    refused = _check(tree, part)
    assert refused.returncode == 1 and "stale" in refused.stderr and rel.split("/")[-1] in refused.stderr
    assert _check(tree, other).returncode == 0
    app, out = _package(tree)
    assert out.returncode == 1 and "stale" in out.stderr + out.stdout
    assert not (app / "python").exists()


def test_a_part_built_before_input_tracking_is_refused(tree):
    (tree / "web" / "ios" / "pybot" / "payload" / "INPUTS.sha256").unlink()
    out = _check(tree, "payload")
    assert out.returncode == 1 and "predates input tracking" in out.stderr
