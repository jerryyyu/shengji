"""Which test tools each iOS flavor may carry (``web/ios/flavor_guard.sh``).

The Xcode phase "Check flavor (nearby)" stops a Release (App Store) build
that lacks Play nearby (``SHENGJI_NEARBY`` and the local-network plist keys)
or carries any test tool: another nearby flag (``SHENGJI_NEARBY_BETA``,
``_DEV``, ``_SPIKE``), ``DEBUG``, or a bundled page with the soak's, log
upload's, hidden switch's or autoplay's markers. It stops a Beta build
(TestFlight internal testing only) that lacks nearby. Both stop when the
synced capacitor.config.json's User-Agent token is not ``ShengjiApp/`` and
the build's MARKETING_VERSION. These tests run the
real script on stand-in plists and pages, and check that the real project
runs it on every build and that the committed Release and Beta
configurations and their Info.plists pass it.
"""

import json
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
FULL = LOCAL_NETWORK + BONJOUR
CLEAN_PAGE = "<!doctype html><title>Sheng Ji</title><script src=assets/index.js></script>"
WEB_SRC = IOS.parent / "src"
VERSION = "1.0.2"


def _app_config(project: Path, ua: str | None) -> None:
    """The synced capacitor.config.json (cap sync writes it; git ignores it)."""
    ios = {} if ua is None else {"appendUserAgent": ua}
    (project / "App").mkdir(parents=True, exist_ok=True)
    (project / "App" / "capacitor.config.json").write_text(json.dumps({"appId": "x", "ios": ios}))


def _markers() -> list[str]:
    """The guard's SOAK_MARKERS, read from the script itself."""
    m = re.search(r"SOAK_MARKERS=\((.*?)\)", GUARD.read_text(), re.S)
    assert m
    return re.findall(r'"([^"]+)"', m.group(1))


def _guard(tmp_path: Path, configuration: str, *, extra: str = "", built_extra: str | None = None,
           swift: str = "", other: str = "", gcc: str = "", source_text: str | None = None,
           built_text: str | None = None, page: str | None = CLEAN_PAGE,
           staged: dict[str, str] | None = None, ua: str | None = f"ShengjiApp/{VERSION}",
           version: str | None = VERSION, config: bool = True):
    project = tmp_path / "App"
    (project / "App").mkdir(parents=True, exist_ok=True)
    if config:
        _app_config(project, ua)
    (project / "App" / "Info.plist").write_text(PLAIN.format(extra=extra) if source_text is None else source_text)
    if page is not None:
        (project / "App" / "public" / "assets").mkdir(parents=True, exist_ok=True)
        (project / "App" / "public" / "index.html").write_text(CLEAN_PAGE)
        (project / "App" / "public" / "assets" / "index.js").write_text(page)
    for rel, text in (staged or {}).items():
        (project / "App" / "public" / rel).parent.mkdir(parents=True, exist_ok=True)
        (project / "App" / "public" / rel).write_text(text)
    env = {**os.environ, "CONFIGURATION": configuration, "PROJECT_DIR": str(project),
           "INFOPLIST_FILE": "App/Info.plist", "SWIFT_ACTIVE_COMPILATION_CONDITIONS": swift,
           "OTHER_SWIFT_FLAGS": other, "GCC_PREPROCESSOR_DEFINITIONS": gcc}
    env.pop("MARKETING_VERSION", None)
    if version is not None:
        env["MARKETING_VERSION"] = version
    if built_extra is not None:
        built = tmp_path / "build" / "App.app"
        built.mkdir(parents=True, exist_ok=True)
        (built / "Info.plist").write_text(PLAIN.format(extra=built_extra) if built_text is None else built_text)
        env.update(TARGET_BUILD_DIR=str(tmp_path / "build"), INFOPLIST_PATH="App.app/Info.plist")
    return subprocess.run(["bash", str(GUARD)], capture_output=True, text=True, env=env)


def test_release_with_nearby_and_no_tools_passes(tmp_path):
    r = _guard(tmp_path, "Release", extra=FULL, built_extra=FULL, swift="SHENGJI_NEARBY")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "nearby on, no test tools" in r.stdout


def test_release_reads_a_quoted_swift_condition(tmp_path):
    r = _guard(tmp_path, "Release", extra=FULL, swift='"SHENGJI_NEARBY"')
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("flags", [
    {},
    {"swift": "SHENGJI_NEARBY_DEV"},
    {"swift": "SHENGJI_NEARBYX"},
    {"other": "-DSHENGJI_NEARBY_BETA"},
    # a C-only define leaves Swift's #if SHENGJI_NEARBY off: not proof of nearby
    {"gcc": "SHENGJI_NEARBY=1"},
    {"gcc": "SHENGJI_NEARBY"},
    # nor is a flag outside the active compilation conditions the gate reads
    {"other": '$(inherited) "-D" "SHENGJI_NEARBY"'},
    {"other": "-DSHENGJI_NEARBY"},
])
def test_release_without_the_swift_condition_fails(tmp_path, flags):
    r = _guard(tmp_path, "Release", extra=FULL, **flags)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "no SHENGJI_NEARBY in SWIFT_ACTIVE_COMPILATION_CONDITIONS" in r.stdout


@pytest.mark.parametrize("flags,named", [
    ({"swift": "SHENGJI_NEARBY SHENGJI_NEARBY_BETA"}, "SHENGJI_NEARBY_BETA"),
    ({"swift": "SHENGJI_NEARBY DEBUG SHENGJI_NEARBY_DEV"}, "DEBUG SHENGJI_NEARBY_DEV"),
    ({"swift": "SHENGJI_NEARBY", "other": '$(inherited) "-D" "SHENGJI_NEARBY_SPIKE"'}, "SHENGJI_NEARBY_SPIKE"),
    ({"swift": "SHENGJI_NEARBY", "other": "-DSHENGJI_NEARBY_BETA"}, "SHENGJI_NEARBY_BETA"),
    ({"swift": "SHENGJI_NEARBY", "gcc": "DEBUG=1"}, "DEBUG"),
])
def test_release_with_a_test_tool_flag_fails(tmp_path, flags, named):
    r = _guard(tmp_path, "Release", extra=FULL, **flags)
    assert r.returncode == 1
    assert f"defines {named}: an App Store build has none of the test tools" in r.stdout


@pytest.mark.parametrize("extra", ["", LOCAL_NETWORK, BONJOUR])
def test_release_without_a_local_network_key_fails(tmp_path, extra):
    r = _guard(tmp_path, "Release", extra=extra, swift="SHENGJI_NEARBY")
    assert r.returncode == 1
    assert "nearby play needs it" in r.stdout


def test_release_checks_the_processed_plist_too(tmp_path):
    r = _guard(tmp_path, "Release", extra=FULL, built_extra=LOCAL_NETWORK, swift="SHENGJI_NEARBY")
    assert r.returncode == 1
    assert "build/App.app/Info.plist has no NSBonjourServices" in r.stdout


@pytest.mark.parametrize("marker", _markers())
def test_release_refuses_a_page_with_a_test_tool(tmp_path, marker):
    r = _guard(tmp_path, "Release", extra=FULL, swift="SHENGJI_NEARBY", page=f"var k={marker!r};")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "the bundled page carries test tools" in r.stdout
    assert "assets/index.js" in r.stdout


@pytest.mark.parametrize("rel", ["nearby-spike.html", "assets/spike-ssn8McqT.js", "assets/spike-old.js.br"])
def test_release_refuses_a_staged_spike_asset(tmp_path, rel):
    """The spike's entry or bundle in App/public, a stale one included, beside a clean page."""
    r = _guard(tmp_path, "Release", extra=FULL, swift="SHENGJI_NEARBY", staged={rel: "<!doctype html>"})
    assert r.returncode == 1, r.stdout + r.stderr
    assert "the bundled page carries the nearby spike" in r.stdout
    assert rel in r.stdout


def test_release_refuses_a_page_with_a_spike_bundle_by_content(tmp_path):
    r = _guard(tmp_path, "Release", extra=FULL, swift="SHENGJI_NEARBY",
               staged={"assets/renamed-1234.js": "p.spikeBench({iterations:1})"})
    assert r.returncode == 1, r.stdout + r.stderr
    assert "the bundled page carries test tools" in r.stdout


def test_release_refuses_a_missing_page(tmp_path):
    r = _guard(tmp_path, "Release", extra=FULL, swift="SHENGJI_NEARBY", page=None)
    assert r.returncode == 1
    assert "no bundled page" in r.stdout


def test_every_marker_is_in_the_test_tools_source():
    """A marker the tools no longer carry would let them through unseen."""
    sources = {p: p.read_text() for p in WEB_SRC.rglob("*.ts*") if ".test." not in p.name}
    markers = _markers()
    assert len(markers) >= 5
    for marker in markers:
        assert any(marker in text for text in sources.values()), marker
    # and none is in the stand-in the App Store page takes for nearbyDebug.tsx
    stub = (WEB_SRC / "nearbyDebugAppStore.ts").read_text()
    assert not any(marker in stub for marker in markers)


@pytest.mark.parametrize("where", ["source", "built"])
def test_a_spaced_path_is_checked_whole(tmp_path, where):
    root = tmp_path / "with space"
    if where == "source":
        r = _guard(root, "Release", extra=LOCAL_NETWORK, swift="SHENGJI_NEARBY")
    else:
        r = _guard(root, "Release", extra=FULL, built_extra=LOCAL_NETWORK, swift="SHENGJI_NEARBY")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "has no NSBonjourServices" in r.stdout
    clean = _guard(tmp_path / "also spaced", "Release", extra=FULL, built_extra=FULL, swift="SHENGJI_NEARBY")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "nearby on" in clean.stdout
    dirty = _guard(tmp_path / "spaced page", "Release", extra=FULL, swift="SHENGJI_NEARBY",
                   page=_markers()[0])
    assert dirty.returncode == 1, dirty.stdout + dirty.stderr


@pytest.mark.parametrize("where", ["source", "built"])
def test_an_unparseable_plist_is_refused(tmp_path, where):
    broken = "<plist><dict><key>oops"
    if where == "source":
        r = _guard(tmp_path, "Release", source_text=broken, swift="SHENGJI_NEARBY")
    else:
        r = _guard(tmp_path, "Release", extra=FULL, built_extra="", built_text=broken, swift="SHENGJI_NEARBY")
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
    flags = re.search(r"SWIFT_ACTIVE_COMPILATION_CONDITIONS = ([^;]+);", release).group(1).strip('"')
    assert flags.split() == ["SHENGJI_NEARBY"]
    plist = re.search(r"INFOPLIST_FILE = (\S+);", release).group(1)
    assert plist == "App/Info.plist"
    # the real plist with a clean stand-in page (App/public is built, not committed)
    project = tmp_path / "App"
    (project / "App" / "public").mkdir(parents=True)
    shutil.copy(IOS / "App" / plist, project / plist)
    (project / "App" / "public" / "index.html").write_text(CLEAN_PAGE)
    version = re.search(r"MARKETING_VERSION = ([^;]+);", release).group(1)
    _app_config(project, f"ShengjiApp/{version}")
    r = subprocess.run(["bash", str(GUARD)], capture_output=True, text=True, env={
        **os.environ, "CONFIGURATION": "Release", "PROJECT_DIR": str(project), "INFOPLIST_FILE": plist,
        "MARKETING_VERSION": version,
        "SWIFT_ACTIVE_COMPILATION_CONDITIONS": flags, "OTHER_SWIFT_FLAGS": "", "GCC_PREPROCESSOR_DEFINITIONS": ""})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "nearby on, no test tools" in r.stdout
    store = plistlib.loads((IOS / "App" / plist).read_bytes())
    assert store["NSBonjourServices"] == ["_shengji-nearby._tcp"]
    assert store["NSLocalNetworkUsageDescription"]


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
    # SHENGJI_NEARBY_BETA compiles the soak's chaos, its log file and the
    # offline autoplay into the Beta
    assert flags.split() == ["SHENGJI_NEARBY", "SHENGJI_NEARBY_BETA"]
    plist = re.search(r'INFOPLIST_FILE = "?([^";]+)"?;', beta).group(1)
    assert plist == "App/Info-Beta.plist"
    # the real plist beside a stand-in synced config (cap sync writes it)
    project = tmp_path / "App"
    (project / "App").mkdir(parents=True)
    shutil.copy(IOS / "App" / plist, project / plist)
    version = re.search(r"MARKETING_VERSION = ([^;]+);", beta).group(1)
    _app_config(project, f"ShengjiApp/{version}")
    r = subprocess.run(["bash", str(GUARD)], capture_output=True, text=True, env={
        **os.environ, "CONFIGURATION": "Beta", "PROJECT_DIR": str(project), "INFOPLIST_FILE": plist,
        "MARKETING_VERSION": version,
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
    # The Beta Info.plist is the App Store one under its own name; both ask
    # for the local network.
    store = plistlib.loads((IOS / "App" / "App" / "Info.plist").read_bytes())
    beta_plist = plistlib.loads((IOS / "App" / "App" / "Info-Beta.plist").read_bytes())
    assert beta_plist["NSBonjourServices"] == ["_shengji-nearby._tcp"]
    assert beta_plist["NSLocalNetworkUsageDescription"]
    assert beta_plist.pop("CFBundleDisplayName") == "Sheng Ji Beta"
    store.pop("CFBundleDisplayName")
    assert beta_plist == store


def test_the_shared_schemes_archive_release_and_beta():
    schemes = IOS / "App" / "App.xcodeproj" / "xcshareddata" / "xcschemes"
    archive = {s.stem: re.search(r'<ArchiveAction\s+buildConfiguration = "(\w+)"', s.read_text()).group(1)
               for s in schemes.glob("*.xcscheme")}
    assert archive == {"App": "Release", "Beta": "Beta"}


NEARBY_PLIST = {"NSBonjourServices": ["_shengji-nearby._tcp"], "NSLocalNetworkUsageDescription": "Nearby."}


@pytest.mark.parametrize("contents,code", [
    (plistlib.dumps(NEARBY_PLIST), 0),
    (plistlib.dumps({"NSBonjourServices": []}), 1),
    (plistlib.dumps(NEARBY_PLIST, fmt=plistlib.FMT_BINARY), 0),
    (plistlib.dumps({"NSBonjourServices": []}, fmt=plistlib.FMT_BINARY), 1),
    (b"<plist><dict><key>oops", 1),
], ids=["xml-nearby", "xml-no-usage", "binary-nearby", "binary-no-usage", "malformed"])
def test_portable_parser_without_apple_tools(tmp_path, contents, code):
    guard = tmp_path / "portable-guard.sh"
    guard.write_text(GUARD.read_text().replace("/usr/bin/plutil", str(tmp_path / "no-plutil"))
                     .replace("/usr/libexec/PlistBuddy", str(tmp_path / "no-PlistBuddy")))
    project = tmp_path / "spaced project"
    (project / "App" / "public").mkdir(parents=True)
    (project / "App" / "public" / "index.html").write_text(CLEAN_PAGE)
    (project / "Info.plist").write_bytes(contents)
    _app_config(project, f"ShengjiApp/{VERSION}")
    result = subprocess.run(["bash", str(guard)], capture_output=True, text=True, env={
        **os.environ, "CONFIGURATION": "Release", "PROJECT_DIR": str(project), "MARKETING_VERSION": VERSION,
        "INFOPLIST_FILE": "Info.plist", "INFOPLIST_PATH": "",
        "SWIFT_ACTIVE_COMPILATION_CONDITIONS": "SHENGJI_NEARBY", "OTHER_SWIFT_FLAGS": "",
        "GCC_PREPROCESSOR_DEFINITIONS": ""})
    assert result.returncode == code, result.stdout + result.stderr
    if code == 0:
        assert "nearby on, no test tools" in result.stdout
    elif contents == b"<plist><dict><key>oops":
        assert "not a readable plist" in result.stdout
    else:
        assert "has no NSLocalNetworkUsageDescription" in result.stdout


# the app's User-Agent token (web/capacitor.config.ts appendUserAgent)

@pytest.mark.parametrize("configuration,swift", [
    ("Release", "SHENGJI_NEARBY"), ("Beta", "SHENGJI_NEARBY SHENGJI_NEARBY_BETA")])
@pytest.mark.parametrize("case", ["stale", "override", "none", "malformed", "no_config", "no_version"])
def test_an_archive_refuses_a_user_agent_token_not_of_its_version(tmp_path, configuration, swift, case):
    kw = {"stale": {"ua": "ShengjiApp/1.0.1"},
          "override": {"version": "1.0.3"},        # MARKETING_VERSION=1.0.3 on the xcodebuild line
          "none": {"ua": None},
          "malformed": {"ua": f"ShengjiApp/{VERSION} extra"},
          "no_config": {"config": False},
          "no_version": {"version": None}}[case]
    r = _guard(tmp_path, configuration, extra=FULL, swift=swift, **kw)
    assert r.returncode == 1, r.stdout + r.stderr
    expect = {"no_config": "no synced config", "no_version": "has no MARKETING_VERSION"}.get(
        case, "User-Agent token")
    assert expect in r.stdout


def test_an_unparseable_synced_config_is_refused(tmp_path):
    (tmp_path / "App" / "App").mkdir(parents=True)
    r = _guard(tmp_path, "Release", extra=FULL, swift="SHENGJI_NEARBY", config=False)
    assert "no synced config" in r.stdout
    (tmp_path / "App" / "App" / "capacitor.config.json").write_text("{not json")
    r = _guard(tmp_path, "Release", extra=FULL, swift="SHENGJI_NEARBY", config=False)
    assert r.returncode == 1
    assert "User-Agent token ''" in r.stdout


def test_debug_needs_no_synced_config(tmp_path):
    r = _guard(tmp_path, "Debug", config=False, version=None)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_portable_reader_checks_the_token_too(tmp_path):
    guard = tmp_path / "portable-guard.sh"
    guard.write_text(GUARD.read_text().replace("/usr/bin/plutil", str(tmp_path / "no-plutil"))
                     .replace("/usr/libexec/PlistBuddy", str(tmp_path / "no-PlistBuddy")))
    project = tmp_path / "App"
    (project / "App" / "public").mkdir(parents=True)
    (project / "App" / "public" / "index.html").write_text(CLEAN_PAGE)
    (project / "Info.plist").write_bytes(plistlib.dumps(NEARBY_PLIST))
    env = {**os.environ, "CONFIGURATION": "Release", "PROJECT_DIR": str(project),
           "INFOPLIST_FILE": "Info.plist", "INFOPLIST_PATH": "", "MARKETING_VERSION": VERSION,
           "SWIFT_ACTIVE_COMPILATION_CONDITIONS": "SHENGJI_NEARBY", "OTHER_SWIFT_FLAGS": "",
           "GCC_PREPROCESSOR_DEFINITIONS": ""}
    for ua, code in ((f"ShengjiApp/{VERSION}", 0), ("ShengjiApp/1.0.1", 1)):
        _app_config(project, ua)
        r = subprocess.run(["bash", str(guard)], capture_output=True, text=True, env=env)
        assert r.returncode == code, r.stdout + r.stderr
