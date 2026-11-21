"""An App Store build of the iOS app never carries Play nearby (``web/ios/flavor_guard.sh``).

The Xcode phase "Check flavor (nearby)" stops a Release build whose Swift
flags define ``SHENGJI_NEARBY*`` or whose Info.plist asks for the local
network, and a Beta build (TestFlight internal testing only) that lacks
either. These tests run the real script on stand-in plists, and check that
the real project runs it on every build and that the committed Release
configuration and Info.plist pass it.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

IOS = Path(__file__).resolve().parents[2] / "web" / "ios"
GUARD = IOS / "flavor_guard.sh"
PBXPROJ = IOS / "App" / "App.xcodeproj" / "project.pbxproj"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

PLAIN = """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
\t<key>CFBundleShortVersionString</key>
\t<string>$(MARKETING_VERSION)</string>
{extra}</dict>
</plist>
"""
LOCAL_NETWORK = "\t<key>NSLocalNetworkUsageDescription</key>\n\t<string>Nearby tables.</string>\n"
BONJOUR = "\t<key>NSBonjourServices</key>\n\t<array>\n\t\t<string>_shengji-nearby._tcp</string>\n\t</array>\n"


def _guard(tmp_path: Path, configuration: str, *, extra: str = "", built_extra: str | None = None,
           swift: str = "", other: str = "", gcc: str = ""):
    project = tmp_path / "App"
    (project / "App").mkdir(parents=True, exist_ok=True)
    (project / "App" / "Info.plist").write_text(PLAIN.format(extra=extra))
    env = {**os.environ, "CONFIGURATION": configuration, "PROJECT_DIR": str(project),
           "INFOPLIST_FILE": "App/Info.plist", "SWIFT_ACTIVE_COMPILATION_CONDITIONS": swift,
           "OTHER_SWIFT_FLAGS": other, "GCC_PREPROCESSOR_DEFINITIONS": gcc}
    if built_extra is not None:
        built = tmp_path / "build" / "App.app"
        built.mkdir(parents=True, exist_ok=True)
        (built / "Info.plist").write_text(PLAIN.format(extra=built_extra))
        env.update(TARGET_BUILD_DIR=str(tmp_path / "build"), INFOPLIST_PATH="App.app/Info.plist")
    return subprocess.run(["bash", str(GUARD)], capture_output=True, text=True, env=env)


def test_release_without_nearby_passes(tmp_path):
    r = _guard(tmp_path, "Release", built_extra="")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "nearby off" in r.stdout


@pytest.mark.parametrize("flags", [
    {"swift": "SHENGJI_NEARBY"},
    {"swift": "DEBUG SHENGJI_NEARBY_DEV"},
    {"other": '$(inherited) "-D" "SHENGJI_NEARBY"'},
    {"other": "-DSHENGJI_NEARBY_BETA"},
    {"gcc": "SHENGJI_NEARBY=1"},
])
def test_release_with_a_nearby_flag_fails(tmp_path, flags):
    r = _guard(tmp_path, "Release", **flags)
    assert r.returncode == 1
    assert "defines SHENGJI_NEARBY" in r.stdout


@pytest.mark.parametrize("extra", [LOCAL_NETWORK, BONJOUR, LOCAL_NETWORK + BONJOUR])
def test_release_with_a_local_network_key_fails(tmp_path, extra):
    r = _guard(tmp_path, "Release", extra=extra)
    assert r.returncode == 1
    assert "never asks for the local network" in r.stdout


def test_release_checks_the_processed_plist_too(tmp_path):
    r = _guard(tmp_path, "Release", built_extra=BONJOUR)
    assert r.returncode == 1
    assert "build/App.app/Info.plist has NSBonjourServices" in r.stdout


def test_debug_may_carry_the_device_test_flags(tmp_path):
    r = _guard(tmp_path, "Debug", extra=LOCAL_NETWORK + BONJOUR, swift="DEBUG SHENGJI_NEARBY SHENGJI_NEARBY_DEV")
    assert r.returncode == 0, r.stdout + r.stderr


def test_beta_must_carry_nearby(tmp_path):
    full = LOCAL_NETWORK + BONJOUR
    assert _guard(tmp_path, "Beta", extra=full, built_extra=full,
                  swift="SHENGJI_NEARBY SHENGJI_NEARBY_BETA").returncode == 0
    assert _guard(tmp_path, "Beta", extra=full).returncode == 1          # no flag
    assert _guard(tmp_path, "Beta", extra=BONJOUR, swift="SHENGJI_NEARBY").returncode == 1


def _target_configs() -> dict[str, str]:
    """The App target's build configurations, name -> settings block."""
    text = PBXPROJ.read_text()
    target = re.search(r'Build configuration list for PBXNativeTarget "App" \*/ = \{.*?buildConfigurations = \((.*?)\);',
                       text, re.S)
    assert target
    out = {}
    for ident, name in re.findall(r"([0-9A-F]{24}) /\* (\w+) \*/", target.group(1)):
        block = re.search(ident + r" /\* " + name + r" \*/ = \{(.*?)\n\t\t\};", text, re.S)
        assert block
        out[name] = block.group(1)
    return out


def test_the_app_target_runs_the_guard_on_every_build():
    text = PBXPROJ.read_text()
    phases = re.search(r'/\* App \*/ = \{\s*isa = PBXNativeTarget;.*?buildPhases = \((.*?)\);', text, re.S)
    assert phases and "/* Check flavor (nearby) */" in phases.group(1)
    phase = re.search(r'/\* Check flavor \(nearby\) \*/ = \{(.*?)\n\t\t\};', text, re.S)
    assert phase
    assert 'flavor_guard.sh' in phase.group(1)
    assert "runOnlyForDeploymentPostprocessing = 0;" in phase.group(1)


def test_the_committed_release_configuration_passes_the_guard(tmp_path):
    release = _target_configs()["Release"]
    assert "SHENGJI_NEARBY" not in release
    plist = re.search(r"INFOPLIST_FILE = (\S+);", release).group(1)
    r = subprocess.run(["bash", str(GUARD)], capture_output=True, text=True, env={
        **os.environ, "CONFIGURATION": "Release", "PROJECT_DIR": str(IOS / "App"), "INFOPLIST_FILE": plist,
        "SWIFT_ACTIVE_COMPILATION_CONDITIONS": "", "OTHER_SWIFT_FLAGS": "", "GCC_PREPROCESSOR_DEFINITIONS": ""})
    assert r.returncode == 0, r.stdout + r.stderr


def test_debug_and_release_share_the_version():
    configs = _target_configs()
    versions = {name: (re.search(r"MARKETING_VERSION = ([^;]+);", block).group(1),
                       re.search(r"CURRENT_PROJECT_VERSION = ([^;]+);", block).group(1))
                for name, block in configs.items() if name in ("Debug", "Release")}
    assert versions["Debug"] == versions["Release"]
    assert "DEVELOPMENT_TEAM" not in PBXPROJ.read_text()
