"""The sign-in plugin ships its own UserDefaults privacy manifest (``web/scripts/patch_social_login_privacy.mjs``).

``@capgo/capacitor-social-login`` calls ``UserDefaults.standard`` but ships no
``PrivacyInfo.xcprivacy``. Apple counts an SDK's required-reason declaration only
from the SDK's own bundle, so ``npm install`` copies a repo-owned manifest into
the plugin's Swift target and declares it as a SwiftPM resource. These tests check
the manifest, that postinstall runs the patch, and that the patch gives a stand-in
plugin the resource exactly once and refuses an unexpected version.
"""

import json
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "web"
MANIFEST = WEB / "ios" / "sdk-privacy" / "SocialLogin" / "PrivacyInfo.xcprivacy"
PATCH = WEB / "scripts" / "patch_social_login_privacy.mjs"
APP_MANIFEST = WEB / "ios" / "App" / "App" / "PrivacyInfo.xcprivacy"

PACKAGE_SWIFT = """// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "CapgoCapacitorSocialLogin",
    targets: [
        .target(
            name: "SocialLoginPlugin",
            dependencies: [],
            path: "ios/Sources/SocialLoginPlugin"),
        .testTarget(
            name: "SocialLoginPluginTests",
            dependencies: ["SocialLoginPlugin"],
            path: "ios/Tests/SocialLoginPluginTests")
    ]
)
"""


def _reasons(path: Path) -> dict[str, list[str]]:
    data = plistlib.loads(path.read_bytes())
    return {entry["NSPrivacyAccessedAPIType"]: entry["NSPrivacyAccessedAPITypeReasons"]
            for entry in data["NSPrivacyAccessedAPITypes"]}


def test_sdk_manifest_declares_userdefaults_ca92_and_nothing_else():
    data = plistlib.loads(MANIFEST.read_bytes())
    assert data["NSPrivacyTracking"] is False
    assert data["NSPrivacyTrackingDomains"] == []
    assert data["NSPrivacyCollectedDataTypes"] == []
    assert _reasons(MANIFEST) == {"NSPrivacyAccessedAPICategoryUserDefaults": ["CA92.1"]}


def test_app_manifest_keeps_its_userdefaults_entry():
    assert _reasons(APP_MANIFEST)["NSPrivacyAccessedAPICategoryUserDefaults"] == ["CA92.1"]


def test_postinstall_runs_the_patch_on_the_pinned_version():
    package = json.loads((WEB / "package.json").read_text())
    assert package["scripts"]["postinstall"] == "node scripts/patch_social_login_privacy.mjs"
    assert package["dependencies"]["@capgo/capacitor-social-login"] == "8.7.5"


def _plugin(tmp_path: Path, version: str = "8.7.5") -> Path:
    plugin = tmp_path / "capacitor-social-login"
    (plugin / "ios" / "Sources" / "SocialLoginPlugin").mkdir(parents=True)
    (plugin / "package.json").write_text(json.dumps({"version": version}))
    (plugin / "Package.swift").write_text(PACKAGE_SWIFT)
    return plugin


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


@needs_node
def test_patch_adds_the_manifest_as_a_resource_once(tmp_path):
    plugin = _plugin(tmp_path)
    for _ in range(2):
        r = subprocess.run(["node", str(PATCH), str(plugin)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
    copied = plugin / "ios" / "Sources" / "SocialLoginPlugin" / "PrivacyInfo.xcprivacy"
    assert copied.read_bytes() == MANIFEST.read_bytes()
    text = (plugin / "Package.swift").read_text()
    assert text.count('resources: [.copy("PrivacyInfo.xcprivacy")]') == 1
    assert 'path: "ios/Sources/SocialLoginPlugin",\n            resources: [.copy("PrivacyInfo.xcprivacy")]),' in text
    assert 'path: "ios/Tests/SocialLoginPluginTests")' in text


@needs_node
def test_patch_refuses_another_version(tmp_path):
    plugin = _plugin(tmp_path, version="8.7.6")
    r = subprocess.run(["node", str(PATCH), str(plugin)], capture_output=True, text=True)
    assert r.returncode == 1
    assert "8.7.6" in r.stderr
    assert "PrivacyInfo" not in (plugin / "Package.swift").read_text()
