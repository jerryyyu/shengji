// @vitest-environment node
/// <reference types="node" />
// The App Store's bundled page (VITE_SHENGJI_APP_STORE=1) has Play nearby and
// none of the test tools; every other build keeps them. The build check runs
// the real Vite build both ways and looks for flavor_guard.sh's markers.
import { describe, expect, it } from "vitest";
import { mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import * as full from "./nearbyDebug";
import * as stub from "./nearbyDebugAppStore";
import { TEST_TOOLS } from "./testTools";

const web = fileURLToPath(new URL("../", import.meta.url));
const guard = readFileSync(join(web, "ios/flavor_guard.sh"), "utf8");
const markers = [...(guard.match(/SOAK_MARKERS=\(([\s\S]*?)\)/)?.[1] ?? "").matchAll(/"([^"]+)"/g)].map((m) => m[1]);

/** Every emitted file's text (not the .br/.gz copies), by name. */
function emitted(dir: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const f of readdirSync(dir, { recursive: true }).map(String)) {
    if (!/\.(js|html|css)$/.test(f)) continue;
    out.set(f, readFileSync(join(dir, f), "utf8"));
  }
  return out;
}

async function buildPage(appStore: boolean, extra: Record<string, string> = {}): Promise<Map<string, string>> {
  const { build } = await import("vite");
  const outDir = mkdtempSync(join(tmpdir(), "shengji-page-"));
  const env = { VITE_SHENGJI_APP_STORE: appStore ? "1" : undefined, ...extra };
  const before = Object.fromEntries(Object.keys(env).map((k) => [k, process.env[k]]));
  const put = (vals: Record<string, string | undefined>) => {
    for (const [k, v] of Object.entries(vals)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  };
  put(env);
  try {
    // the config reads the flags when it loads, so a fresh load per build
    await build({ root: web, configFile: join(web, "vite.config.ts"), logLevel: "silent", build: { outDir, emptyOutDir: true } });
  } finally {
    put(before);
  }
  return emitted(outDir);
}

const holding = (files: Map<string, string>, s: string) => [...files].filter(([, t]) => t.includes(s)).map(([f]) => f);

describe("the App Store's bundled page", () => {
  it("the stand-in has every name nearbyUi.tsx takes from nearbyDebug.tsx", () => {
    const ui = readFileSync(join(web, "src/nearbyUi.tsx"), "utf8");
    const m = ui.match(/import NearbyDebugPaneFull, \{([^}]*)\} from "\.\/nearbyDebug";/);
    expect(m).not.toBeNull();
    const names = m![1].split(",").map((n) => n.trim().split(/\s+as\s+/)[0]).filter(Boolean);
    expect(names.length).toBeGreaterThan(5);
    for (const n of [...names, "default"]) {
      expect(typeof (stub as Record<string, unknown>)[n], n).toBe("function");
      expect(typeof (full as Record<string, unknown>)[n], n).toBe("function");
    }
    expect(stub.useNearbySoak(true)).toBeNull();
    expect(stub.useNearbyDebug(true)).toBe(false);
    expect(stub.nearbySoakSwitchOn()).toBe(false);
  });

  it("tests and every build without the flag keep the test tools", () => {
    expect(TEST_TOOLS).toBe(true);
    expect(markers.length).toBeGreaterThanOrEqual(5);
  });

  it("built with the flag, has nearby play and none of the markers; without it, all of them", async () => {
    const store = await buildPage(true);
    for (const s of markers) expect(holding(store, s), s).toEqual([]);
    for (const s of ["Upload log now", "Stop soak", "AWDL keepalive", "nearby-soak-pill"]) expect(holding(store, s), s).toEqual([]);
    // the nearby UI and the host's on-device server are there
    expect([...store.keys()].some((f) => /nearbyUi-[\w-]+\.js$/.test(f))).toBe(true);
    expect(holding(store, "ShengjiNearby").length).toBeGreaterThan(0);
    expect([...store.keys()].some((f) => /nearbySoak|nearbyLogUpload/.test(f))).toBe(false);

    expect(holding(store, "spikeBench")).toEqual([]);
    expect([...store.keys()].some((f) => /spike/.test(f))).toBe(false);

    const served = await buildPage(false);
    // every marker is in the build that carries its tool: the spike's in the spike's build
    for (const s of markers.filter((m) => m !== "spikeBench")) expect(holding(served, s).length, s).toBeGreaterThan(0);
    expect([...served.keys()].some((f) => /nearbySoak-[\w-]+\.js$/.test(f))).toBe(true);
  }, 60_000);

  it("refuses the App Store flag with a device-test flag, before anything is emitted", async () => {
    for (const flag of ["SHENGJI_NEARBY_SPIKE", "SHENGJI_NEARBY_DEV", "VITE_SHENGJI_NEARBY_SPIKE"]) {
      await expect(buildPage(true, { [flag]: "1" }), flag).rejects.toThrow(/the App Store page has no device-test tools/);
    }
    // the spike's own build, without the App Store flag, still makes its page
    const spike = await buildPage(false, { SHENGJI_NEARBY_SPIKE: "1" });
    expect([...spike.keys()]).toContain("nearby-spike.html");
    expect(markers).toContain("spikeBench");
    expect(holding(spike, "spikeBench").length).toBeGreaterThan(0);
  }, 60_000);
});
