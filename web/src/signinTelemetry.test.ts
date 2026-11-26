/// <reference types="node" />
// The platform stamp, the identity sheet's entry points and the sign-in
// events: enums only, and never a token, a name or an email.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./ws", () => ({ conn: { send: () => false }, getSavedName: () => "", saveName: () => {} }));

import { Telemetry, platform, telemetry } from "./telemetry";
import { guestName } from "./guestName";

// vitest runs from web/; jsdom gives import.meta.url no file scheme
const SRC = join(process.cwd(), "src");

type Win = { Capacitor?: unknown; matchMedia?: unknown };

function setShell(cap: unknown, standalone = false, navStandalone?: boolean) {
  const w = window as unknown as Win;
  if (cap === undefined) delete w.Capacitor;
  else w.Capacitor = cap;
  w.matchMedia = (q: string) => ({ matches: standalone && q === "(display-mode: standalone)" });
  Object.defineProperty(navigator, "standalone", { value: navStandalone, configurable: true });
}

afterEach(() => {
  setShell(undefined);
  telemetry.reset();
});

describe("platform", () => {
  it("is ios_app only in the Capacitor shell on iOS", () => {
    setShell({ isNativePlatform: () => true, getPlatform: () => "ios" });
    expect(platform()).toBe("ios_app");
    setShell({ isNativePlatform: () => true, getPlatform: () => "android" });
    expect(platform()).toBe("web");
    setShell({ isNativePlatform: () => false, getPlatform: () => "web" });
    expect(platform()).toBe("web");
  });

  it("is pwa for the site opened from a home-screen icon, else web", () => {
    setShell(undefined, true);
    expect(platform()).toBe("pwa");
    setShell(undefined, false, true);
    expect(platform()).toBe("pwa");
    setShell(undefined, false);
    expect(platform()).toBe("web");
  });

  it("reads as web when the checks throw", () => {
    setShell({ isNativePlatform: () => { throw new Error("bridge"); } });
    expect(platform()).toBe("web");
  });

  it("goes on every batch beside the form", () => {
    setShell({ isNativePlatform: () => true, getPlatform: () => "ios" });
    const sent: Record<string, unknown>[] = [];
    const t = new Telemetry((m) => { sent.push(m as Record<string, unknown>); return true; }, true);
    t.tap("play");
    t.flush();
    expect(sent[0]).toMatchObject({ type: "client_event", v: 1, platform: "ios_app" });
    expect(Object.keys(sent[0]).sort()).toEqual(["days_since_first", "events", "first_visit", "form", "lang",
                                                 "platform", "session_n", "type", "v"]);
  });
});

describe("the identity sheet's entry points", () => {
  beforeEach(() => { guestName.reset(); telemetry.reset(); });

  it("open(from) sends signin_open with where it was opened; open() alone sends nothing", () => {
    guestName.open("leaderboard_row");
    expect(telemetry.pending()).toEqual([expect.objectContaining({ e: "tap", id: "signin_open", from: "leaderboard_row" })]);
    telemetry.reset();
    guestName.open();
    expect(telemetry.pending()).toEqual([]);
  });

  // Every place that opens the sheet names itself; a new one is added here.
  const EXPECTED: Record<string, string[]> = {
    "App.tsx": ["moved"],
    "components/AccountChip.tsx": ["chip"],
    "components/CharacterPage.tsx": ["collection"],
    "components/StoreFoot.tsx": ["shop", "shop"],
    "components/GuestChip.tsx": ["chip"],
    "components/MePage.tsx": ["me_row", "me_signin", "me_row"],
    "components/Leaderboard.tsx": ["leaderboard_row"],
    "components/RoundEndModal.tsx": ["round_end"],
    "components/GamesStatus.tsx": ["lapsed"],
    "components/OpponentActions.tsx": ["report"],
    "queue/Ranked.tsx": ["play_line"],
  };

  function sources(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) return sources(path);
      return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
    });
  }

  it("each call site passes its entry point", () => {
    const found: Record<string, string[]> = {};
    for (const path of sources(SRC)) {
      // code lines only: a doc comment may name the call
      const code = readFileSync(path, "utf8").split("\n").filter((l) => !/^\s*(\*|\/\/|\/\*)/.test(l)).join("\n");
      const calls = [...code.matchAll(/guestName\.open\(([^)]*)\)/g)].map((m) => m[1]);
      if (calls.length) found[relative(SRC, path).split(sep).join("/")] = calls.map((c) => c.replace(/"/g, ""));
    }
    expect(found).toEqual(EXPECTED);
  });
});

describe("no identifier in any payload", () => {
  it("every event kind serializes to enums, booleans and bounded numbers only", () => {
    setShell({ isNativePlatform: () => true, getPlatform: () => "ios" });
    const sent: unknown[] = [];
    const t = new Telemetry((m) => { sent.push(m); return true; }, true);
    t.screenView("me");
    t.signinOpen("me_row");
    t.signin("provider_tap", "apple");
    t.signin("closed", "apple");
    t.signin("provider_tap", "google");
    t.signin("error", "google");
    t.signin("done", "google");
    for (const step of ["created", "restored", "fell_back_guest", "linked", "conflict_shown", "switched"] as const) {
      t.deviceAccount(step);
    }
    t.appOpen(true, 900);
    t.roundStart("friend", 2, 3);
    t.roundFinish("friend", "closed", 4);
    expect(t.sendOfflineDigest({ rounds_started: 2, rounds_finished: 1, nearby_rounds: 0 })).toBe(true);
    t.howtoStep(4, false);
    t.flush();
    const text = JSON.stringify(sent);
    // nothing shaped like a JWT, an email, a hex secret, or free text
    expect(text).not.toMatch(/eyJ|@|[0-9a-f]{20}/);
    const walk = (v: unknown): void => {
      if (Array.isArray(v)) v.forEach(walk);
      else if (v && typeof v === "object") Object.values(v).forEach(walk);
      // enum words, or a bucket such as "2-7" or "31+"
      else if (typeof v === "string") expect(v).toMatch(/^(?:[a-z_-]{1,24}|\d{1,2}(?:-\d{1,2}|\+)?)$/);
      else expect(["number", "boolean"]).toContain(typeof v);
    };
    walk(sent);
  });
});
