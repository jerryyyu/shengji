// @vitest-environment node
/// <reference types="node" />
// The iOS Simulator smoke's verdict (scripts/ios_sim_smoke.mjs): a run that
// checked less than it claims fails, and its server reads only web/dist.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { MENUS, SHOTS, failures, observedOrient, parseOrients, staticFile } from "../scripts/ios_sim_smoke_lib.mjs";

const WEB = fileURLToPath(new URL("..", import.meta.url));
const cli = (args: string[], env: Record<string, string> = {}) => {
  const clean = { ...process.env, ...env };
  if (!("SIM_ROTATE" in env)) delete clean.SIM_ROTATE;
  return spawnSync(process.execPath, [path.join(WEB, "scripts/ios_sim_smoke.mjs"), ...args], { encoding: "utf8", env: clean, timeout: 30000 });
};

describe("the smoke's command line", () => {
  it("fails, running nothing, when asked for landscape with no command to turn the simulator", () => {
    for (const orient of ["left", "right", "left,right", "portrait,left"]) {
      const r = cli(["--orient", orient, "--dist", "/nonexistent"]);
      expect(r.status, orient).toBe(2);
      expect(r.stderr).toMatch(/SIM_ROTATE/);
      expect(r.stdout).not.toMatch(/PASSED|drawn/);
    }
  });

  it("fails on an empty, unknown or repeated orientation", () => {
    for (const orient of ["", ",", "sideways", "portrait,portrait"]) {
      expect(cli(["--orient", orient, "--dist", "/nonexistent"]).status, orient).toBe(2);
    }
  });
});

const drawn = { ok: true, why: null };
const run = (orient: string, over: object = {}) => ({ orient, observed: orient, menus: Object.fromEntries(MENUS.map((m: string) => [m, drawn])), ...over });

describe("the verdict", () => {
  it("passes only every orientation asked for, seen as asked, with both menus drawn", () => {
    expect(failures(["portrait", "left"], [run("portrait"), run("left")])).toEqual([]);
  });

  it("fails a run that checked nothing, or less than both menus", () => {
    expect(failures([], [])).toEqual(["no orientation ran"]);
    expect(failures(["portrait"], [])).toEqual(["portrait: did not run"]);
    expect(failures(["portrait"], [run("portrait", { menus: { "watch-menu": drawn } })])).toEqual(["portrait table-menu: not checked"]);
    expect(failures(["portrait"], [run("portrait", { menus: {} })])).toHaveLength(2);
    expect(failures(["left"], [run("left", { error: "timed out" })])).toEqual(["left: timed out"]);
  });

  it("fails a turn that did not happen: the page's own orientation decides, not the request", () => {
    expect(failures(["left"], [run("left", { observed: "portrait" })])).toEqual(["left: the page was portrait, not left"]);
    expect(failures(["right"], [run("right", { observed: null })])).toHaveLength(1);
    expect(observedOrient({ angle: 0, w: 402, h: 874 })).toBe("portrait");
    expect(observedOrient({ angle: 90, w: 874, h: 402 })).toBe("left");
    expect(observedOrient({ angle: -90, w: 874, h: 402 })).toBe("right");
    // the angle and the shape disagree, or the page gave no angle
    expect(observedOrient({ angle: 90, w: 402, h: 874 })).toBeNull();
    expect(observedOrient({ angle: 0, w: 874, h: 402 })).toBeNull();
    expect(observedOrient({ angle: null, w: 402, h: 874 })).toBeNull();
  });

  it("fails a menu judged invisible", () => {
    const r = run("portrait", { menus: { "watch-menu": drawn, "table-menu": { ok: false, why: "INVISIBLE" } } });
    expect(failures(["portrait"], [r])).toEqual(["portrait table-menu: INVISIBLE"]);
  });
});

describe("what the page may ask the smoke for", () => {
  it("names its screenshots from a fixed list", () => {
    expect(SHOTS).toContain("watch-menu-open");
    for (const bad of ["../x", "watch-menu", "calibrate/../../x", ""]) expect(SHOTS).not.toContain(bad);
  });

  it("reads files from web/dist only", () => {
    const dist = "/srv/dist";
    expect(staticFile(dist, "/assets/index.js")).toBe("/srv/dist/assets/index.js");
    expect(staticFile(dist, "/")).toBe("/srv/dist");
    for (const bad of ["/../package.json", "/%2e%2e/package.json", "/assets/../../x", "/%2e%2e%2fx", "/a%00b", "/%E0%A4%A"]) {
      expect(staticFile(dist, bad), bad).toBeNull();
    }
    expect(parseOrients(undefined, undefined)).toEqual({ orients: ["portrait"] });
    expect(parseOrients(undefined, "turn {udid} {orientation}")).toEqual({ orients: ["portrait", "left", "right"] });
  });
});
