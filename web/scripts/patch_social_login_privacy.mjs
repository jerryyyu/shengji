// Gives the pinned @capgo/capacitor-social-login its own privacy manifest.
//
// The plugin reads and writes its sign-in state through UserDefaults.standard,
// a required-reason API, but ships no PrivacyInfo.xcprivacy. Apple counts an
// SDK's declaration only when the SDK's own resource bundle carries it, so this
// copies ios/sdk-privacy/SocialLogin/PrivacyInfo.xcprivacy into the plugin's
// Swift target and declares it as a SwiftPM resource. Swift sources are not
// touched. It runs on every `npm install` / `npm ci` (postinstall) and is
// idempotent. It fails on any other plugin version, so an update has to
// re-check whether the new release ships its own manifest.
//
// Usage: node scripts/patch_social_login_privacy.mjs [plugin dir]

import { copyFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PINNED = "8.7.5";
const TARGET_PATH = 'path: "ios/Sources/SocialLoginPlugin")';
const RESOURCE = '.copy("PrivacyInfo.xcprivacy")';

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const plugin = resolve(process.argv[2] ?? join(web, "node_modules", "@capgo", "capacitor-social-login"));
const manifest = join(web, "ios", "sdk-privacy", "SocialLogin", "PrivacyInfo.xcprivacy");

function fail(message) {
  console.error(`patch_social_login_privacy: ${message}`);
  process.exit(1);
}

if (!existsSync(join(plugin, "package.json"))) fail(`plugin not installed at ${plugin}`);
const version = JSON.parse(readFileSync(join(plugin, "package.json"), "utf8")).version;
if (version !== PINNED) {
  fail(`expected @capgo/capacitor-social-login ${PINNED}, found ${version}; check whether it ships its own PrivacyInfo.xcprivacy, then update this script`);
}

const sources = join(plugin, "ios", "Sources", "SocialLoginPlugin");
if (!existsSync(sources)) fail(`missing ${sources}`);
copyFileSync(manifest, join(sources, "PrivacyInfo.xcprivacy"));

const packageSwift = join(plugin, "Package.swift");
const text = readFileSync(packageSwift, "utf8");
if (!text.includes(RESOURCE)) {
  const hits = text.split(TARGET_PATH).length - 1;
  if (hits !== 1) fail(`expected one '${TARGET_PATH}' in ${packageSwift}, found ${hits}`);
  writeFileSync(
    packageSwift,
    text.replace(TARGET_PATH, `${TARGET_PATH.slice(0, -1)},\n            resources: [${RESOURCE}])`),
  );
}
console.log(`patch_social_login_privacy: ${version} carries PrivacyInfo.xcprivacy`);
