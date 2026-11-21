"""An App Store build of the iOS app never carries Play nearby (``web/ios/flavor_guard.sh``).

The Xcode phase "Check flavor (nearby)" stops a Release build whose Swift
flags define ``SHENGJI_NEARBY*`` or whose Info.plist asks for the local
network, and a Beta build (TestFlight internal testing only) that lacks
either. These tests run the real script on stand-in plists, and check that
the real project runs it on every build and that the committed Release and
Beta configurations and their Info.plists pass it.
"""

import os
import plistlib
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
           swift: str = "", other: str = "", gcc: str = "", source_text: str | None = None,
           built_text: str | None = None):
    project = tmp_path / "App"
    (project / "App").mkdir(parents=True, exist_ok=True)
    (project / "App" / "Info.plist").write_text(PLAIN.format(extra=extra) if source_text is None else source_text)
    env = {**os.environ, "CONFIGURATION": configuration, "PROJECT_DIR": str(project),
           "INFOPLIST_FILE": "App/Info.plist", "SWIFT_ACTIVE_COMPILATION_CONDITIONS": swift,
           "OTHER_SWIFT_FLAGS": other, "GCC_PREPROCESSOR_DEFINITIONS": gcc}
    if built_extra is not None:
        built = tmp_path / "build" / "App.app"
        built.mkdir(parents=True, exist_ok=True)
        (built / "Info.plist").write_text(PLAIN.format(extra=built_extra) if built_text is None else built_text)
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


@pytest.mark.parametrize("where", ["source", "built"])
def test_a_spaced_path_is_checked_whole(tmp_path, where):
    root = tmp_path / "with space"
    if where == "source":
        r = _guard(root, "Release", extra=BONJOUR)
    else:
        r = _guard(root, "Release", built_extra=BONJOUR)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "NSBonjourServices" in r.stdout
    clean = _guard(tmp_path / "also spaced", "Release", built_extra="")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "nearby off" in clean.stdout


@pytest.mark.parametrize("where", ["source", "built"])
def test_an_unparseable_plist_is_refused(tmp_path, where):
    broken = "<plist><dict><key>oops"
    if where == "source":
        r = _guard(tmp_path, "Release", source_text=broken)
    else:
        r = _guard(tmp_path, "Release", built_extra="", built_text=broken)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "not a readable plist" in r.stdout


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


def test_the_committed_beta_configuration_passes_the_guard(tmp_path):
    configs = _target_configs()
    beta = configs["Beta"]
    flags = re.search(r'SWIFT_ACTIVE_COMPILATION_CONDITIONS = "([^"]*)";', beta).group(1)
    assert flags.split() == ["SHENGJI_NEARBY", "SHENGJI_NEARBY_BETA"]
    plist = re.search(r'INFOPLIST_FILE = "?([^";]+)"?;', beta).group(1)
    assert plist == "App/Info-Beta.plist"
    r = subprocess.run(["bash", str(GUARD)], capture_output=True, text=True, env={
        **os.environ, "CONFIGURATION": "Beta", "PROJECT_DIR": str(IOS / "App"), "INFOPLIST_FILE": plist,
        "SWIFT_ACTIVE_COMPILATION_CONDITIONS": flags, "OTHER_SWIFT_FLAGS": "", "GCC_PREPROCESSOR_DEFINITIONS": ""})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "nearby on" in r.stdout


def test_the_beta_is_the_release_build_under_its_own_name():
    configs = _target_configs()
    release, beta = configs["Release"], configs["Beta"]

    def setting(block, key):
        return re.search(key + r" = ([^;]+);", block).group(1)

    # Only the plist, the nearby flags and the build number set the two apart.
    differ = {"INFOPLIST_FILE", "SWIFT_ACTIVE_COMPILATION_CONDITIONS", "CURRENT_PROJECT_VERSION"}
    keys = set(re.findall(r"^\t\t\t\t(\w+) = ", release, re.M)) | set(re.findall(r"^\t\t\t\t(\w+) = ", beta, re.M))
    for key in keys - differ:
        assert setting(beta, key) == setting(release, key), key
    assert setting(beta, "CURRENT_PROJECT_VERSION").startswith(setting(release, "CURRENT_PROJECT_VERSION") + ".")
    # The Beta Info.plist is the App Store one plus the local-network keys.
    store = plistlib.loads((IOS / "App" / "App" / "Info.plist").read_bytes())
    beta_plist = plistlib.loads((IOS / "App" / "App" / "Info-Beta.plist").read_bytes())
    assert beta_plist.pop("NSBonjourServices") == ["_shengji-nearby._tcp"]
    assert beta_plist.pop("NSLocalNetworkUsageDescription")
    assert beta_plist.pop("CFBundleDisplayName") == "Sheng Ji Beta"
    store.pop("CFBundleDisplayName")
    assert beta_plist == store


def test_the_shared_schemes_archive_release_and_beta():
    schemes = IOS / "App" / "App.xcodeproj" / "xcshareddata" / "xcschemes"
    archive = {s.stem: re.search(r'<ArchiveAction\s+buildConfiguration = "(\w+)"', s.read_text()).group(1)
               for s in schemes.glob("*.xcscheme")}
    assert archive == {"App": "Release", "Beta": "Beta"}


@pytest.mark.parametrize("contents,code", [
    (plistlib.dumps({}), 0),
    (plistlib.dumps({"NSBonjourServices": []}), 1),
    (plistlib.dumps({}, fmt=plistlib.FMT_BINARY), 0),
    (plistlib.dumps({"NSBonjourServices": []}, fmt=plistlib.FMT_BINARY), 1),
    (b"<plist><dict><key>oops", 1),
], ids=["xml-clean", "xml-forbidden", "binary-clean", "binary-forbidden", "malformed"])
def test_portable_parser_without_apple_tools(tmp_path, contents, code):
    guard = tmp_path / "portable-guard.sh"
    guard.write_text(GUARD.read_text().replace("/usr/bin/plutil", str(tmp_path / "no-plutil"))
                     .replace("/usr/libexec/PlistBuddy", str(tmp_path / "no-PlistBuddy")))
    project = tmp_path / "spaced project"
    project.mkdir()
    (project / "Info.plist").write_bytes(contents)
    result = subprocess.run(["bash", str(guard)], capture_output=True, text=True, env={
        **os.environ, "CONFIGURATION": "Release", "PROJECT_DIR": str(project),
        "INFOPLIST_FILE": "Info.plist", "INFOPLIST_PATH": "",
        "SWIFT_ACTIVE_COMPILATION_CONDITIONS": "", "OTHER_SWIFT_FLAGS": "",
        "GCC_PREPROCESSOR_DEFINITIONS": ""})
    assert result.returncode == code, result.stdout + result.stderr
    if code == 0:
        assert "nearby off" in result.stdout
    elif contents == b"<plist><dict><key>oops":
        assert "not a readable plist" in result.stdout
    else:
        assert "has NSBonjourServices" in result.stdout
