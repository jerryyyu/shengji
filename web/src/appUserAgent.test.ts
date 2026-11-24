import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import config, { APP_UA_PRODUCT, marketingVersion } from "../capacitor.config.ts";

const PBXPROJ = `${import.meta.dirname}/../ios/App/App.xcodeproj/project.pbxproj`;

describe("the iOS app's User-Agent token", () => {
  it("carries the Xcode project's version as ShengjiApp/<version>", () => {
    const versions = [...readFileSync(PBXPROJ, "utf8").matchAll(/MARKETING_VERSION = ([^;]+);/g)].map((m) => m[1]);
    expect(versions.length).toBeGreaterThan(0);
    expect(new Set(versions).size).toBe(1);
    expect(config.ios?.appendUserAgent).toBe(`${APP_UA_PRODUCT}/${versions[0]}`);
    // the server's app_version pattern (server/shengji/api/telemetry.py)
    expect(config.ios?.appendUserAgent).toMatch(/^ShengjiApp\/\d+\.\d+(\.\d+)?$/);
    // never the override, which would replace the WebView's own User-Agent
    expect(config.ios?.overrideUserAgent).toBeUndefined();
    expect(config.appendUserAgent).toBeUndefined();
  });

  it("stops the sync on a missing, mixed or malformed version", () => {
    const one = (v: string) => `\t\t\t\tMARKETING_VERSION = ${v};\n`;
    expect(marketingVersion(one("1.0.2") + one("1.0.2"))).toBe("1.0.2");
    expect(marketingVersion(one("1.1"))).toBe("1.1");
    expect(() => marketingVersion("")).toThrow();
    expect(() => marketingVersion(one("1.0.2") + one("1.0.1"))).toThrow();
    expect(() => marketingVersion(one("1.0.2 beta"))).toThrow();
    expect(() => marketingVersion(one("$(VERSION)"))).toThrow();
  });
});
