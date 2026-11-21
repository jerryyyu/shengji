// @vitest-environment node
/// <reference types="node" />
// The page and the native plugin agree on the nearby constants, and the
// app's Info.plist, once it carries the nearby keys, names the same Bonjour
// type (without it iOS refuses to browse or advertise, with no prompt). The
// plist keys are not in the app yet; the check binds as soon as they land.
import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { NEARBY_ALPHABET, NEARBY_CODE_LEN } from "./codes";
import { NEARBY_SERVICE_TYPE, NEARBY_V, LIMITS } from "./protocol";
import { HOST_WINDOW_MS } from "../../../codeJoin";

const read = (rel: string) => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), "utf8");
const swift = read("../../../../ios/App/App/NearbyPlugin.swift");
const plist = read("../../../../ios/App/App/Info.plist");
const shell = read("../../../../ios/App/App/ShellViewController.swift");

/** The array of strings under `key` in the plist, or null when absent. */
function plistArray(key: string): string[] | null {
  const m = plist.match(new RegExp(`<key>${key}</key>\\s*<array>([\\s\\S]*?)</array>`));
  return m ? [...m[1].matchAll(/<string>([^<]*)<\/string>/g)].map((x) => x[1]) : null;
}

describe("nearby constants across the page, the plugin and Info.plist", () => {
  it("the plugin uses the page's service type, version, code and frame limit", () => {
    expect(swift).toContain(`static let serviceType = "${NEARBY_SERVICE_TYPE}"`);
    expect(swift).toContain(`static let nearbyV = ${NEARBY_V}`);
    expect(swift).toContain(`static let alphabet = Array("${NEARBY_ALPHABET}")`);
    expect(swift).toContain(`static let codeLength = ${NEARBY_CODE_LEN}`);
    expect(LIMITS.frameBytes).toBe(16 * 1024);
    expect(swift).toContain("static let maxMessage = 16 * 1024");
  });

  it("the joiner waits a few seconds longer for its host than the host has to come back", () => {
    const m = swift.match(/static let hostWindow: TimeInterval = (\d+)/);
    expect(m).not.toBeNull();
    const hostMs = Number(m![1]) * 1000;
    expect(HOST_WINDOW_MS).toBeGreaterThanOrEqual(hostMs + 3000);
    expect(HOST_WINDOW_MS).toBeLessThanOrEqual(hostMs + 10_000);
  });

  it("the plugin cannot run unreviewed and is not registered in a shipped build", () => {
    expect(swift).toMatch(/static let reviewed = false/);
    expect(swift).toMatch(/#if SHENGJI_NEARBY_BETA\s+static let betaBuild = true\s+#else\s+static let betaBuild = false\s+#endif\s+static var enabled: Bool \{ reviewed \|\| debugBuild \|\| betaBuild \}/);
    expect(swift).toMatch(/#else\s+static let debugBuild = false/);
    expect(shell).toMatch(/#if SHENGJI_NEARBY\s+(?:\/\/[^\n]*\s+)?bridge\?\.registerPluginInstance\(ShengjiNearbyPlugin\(\)\)\s+#endif/);
  });

  it("the device-test switches turn on only from the xcodebuild command line, in Debug", () => {
    const project = read("../../../../ios/App/App.xcodeproj/project.pbxproj");
    const xcconfig = read("../../../../ios/debug.xcconfig");
    expect(xcconfig).not.toMatch(/SHENGJI_NEARBY/);
    // the project names the nearby flags once: the Beta configuration's
    expect(project.match(/SHENGJI_NEARBY/g)).toHaveLength(2);
    expect(project).toMatch(/\/\* Beta \*\/ = \{[^}]*SWIFT_ACTIVE_COMPILATION_CONDITIONS = "SHENGJI_NEARBY SHENGJI_NEARBY_BETA";[^}]*\};\s*name = Beta;/);
    expect(project).not.toMatch(/SHENGJI_NEARBY_(DEV|SPIKE)/);
    expect(swift.match(/static let debugBuild = true/g)).toHaveLength(1);
    expect(swift).toMatch(/#if DEBUG && \(SHENGJI_NEARBY_SPIKE \|\| SHENGJI_NEARBY_DEV\)\s+static let debugBuild = true\s+#else\s+static let debugBuild = false\s+#endif/);
    expect(swift).toMatch(/#if DEBUG && SHENGJI_NEARBY_SPIKE\n[\s\S]*func spikeBench[\s\S]*#else\n/);
    expect(shell).toMatch(/#if DEBUG && SHENGJI_NEARBY_SPIKE\s+(?:\/\/\/[^\n]*\s+)?override open func instanceDescriptor/);
    expect(shell).toMatch(/#elseif DEBUG && SHENGJI_NEARBY_DEV\s+(?:\/\/\/[^\n]*\s+)*override open func instanceDescriptor/);
  });

  it("the soak's chaos and autoplay are only in a device-test Debug build", () => {
    // the plugin's fault injection is compiled only with SHENGJI_NEARBY_DEV
    // in Debug; every other build has no debugChaos and never holds a frame
    expect(swift.match(/func debugChaos/g)).toHaveLength(1);
    expect(swift).toMatch(/#if DEBUG && SHENGJI_NEARBY_DEV\n(?:\/\/\/[^\n]*\n)*extension ShengjiNearbyPlugin \{\n    static let chaosMethods: \[CAPPluginMethod\] = \[\n        CAPPluginMethod\(name: "debugChaos"[\s\S]*?func debugChaos[\s\S]*?\n#else\nextension ShengjiNearbyPlugin \{\n    static let chaosMethods: \[CAPPluginMethod\] = \[\]\n    static func chaosHold\(_ work: @escaping \(\) -> Void\) -> Bool \{ false \}\n\}\n#endif/);
    // the page loads the soak module only from the debug rows, by a dynamic
    // import, and shows its switches only when the plugin says `debug`
    const src = fileURLToPath(new URL("../../../", import.meta.url));
    const files = readdirSync(src, { recursive: true }).map(String)
      .filter((f) => /\.(ts|tsx)$/.test(f) && !/\.test\.tsx?$/.test(f) && !f.endsWith("nearbySoak.ts"));
    const users = files.filter((f) => readFileSync(join(src, f), "utf8").includes("nearbySoak"));
    expect(users.sort()).toEqual(["nearbyDebug.tsx"]);
    const debugPane = readFileSync(join(src, "nearbyDebug.tsx"), "utf8");
    expect(debugPane).not.toMatch(/^import[^\n]*nearbySoak/m);
    expect(debugPane).toContain('import("./nearbySoak")');
    expect(debugPane).toMatch(/c\.debug === true \? \(p as DebugPlugin\) : null/);
    const menu = readFileSync(join(src, "components/HudMenu.tsx"), "utf8");
    expect(menu).toMatch(/const soak = useNearbySoak\(debug\);/);
    expect(menu).toMatch(/\{debug && soak \? \(/);
    for (const label of ["Autoplay", "Chaos", "Copy soak summary"]) expect(menu.split(`<span>${label}</span>`)).toHaveLength(2);
  });

  it("the App Store Info.plist has no local-network keys; the Beta one has them and the nearby type", () => {
    // the keys wait for the nearby release's review
    expect(plistArray("NSBonjourServices")).toBeNull();
    expect(plist).not.toContain("NSLocalNetworkUsageDescription");
    const beta = read("../../../../ios/App/App/Info-Beta.plist");
    const services = beta.match(/<key>NSBonjourServices<\/key>\s*<array>([\s\S]*?)<\/array>/);
    expect(services).not.toBeNull();
    expect([...services![1].matchAll(/<string>([^<]*)<\/string>/g)].map((x) => x[1])).toEqual([NEARBY_SERVICE_TYPE]);
    expect(beta).toContain("<key>NSLocalNetworkUsageDescription</key>");
    // otherwise the Beta plist is the App Store one, under its own name
    const strip = (text: string) => text
      .replace(/\t<key>NSLocalNetworkUsageDescription<\/key>\n\t<string>[^<]*<\/string>\n/, "")
      .replace(/\t<key>NSBonjourServices<\/key>\n\t<array>[\s\S]*?<\/array>\n/, "")
      .replace("<string>Sheng Ji Beta</string>", "<string>Sheng Ji</string>");
    expect(strip(beta)).toBe(plist);
  });
});
