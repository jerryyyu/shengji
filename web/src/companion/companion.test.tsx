import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthState, AuthUser } from "../auth";

const { authState, updated } = vi.hoisted(() => ({
  authState: { current: { status: "out", clientId: "cid", user: null } as AuthState },
  updated: vi.fn(),
}));
vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));
vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return { ...real, useAuth: () => authState.current, auth: { updated, get state() { return authState.current; } } };
});

import { Companion, Portrait } from "./Companion";
import { COMPANIONS, DEFAULT_LOOK, LOOK_UNLOCKS, lookCatalogue, parseLook } from "./look";
import { TRACTOR_COLOURS } from "./palette";
import { hasNewLook, markLooksSeen } from "./seen";
import { parseArt, tractorMarkup } from "./Tractor";
import CollectionPage from "../components/CollectionPage";
import { Row } from "../components/Leaderboard";
import { forgetHomeSession, forgetPrivateSession } from "../home/session";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  updated.mockClear();
  forgetHomeSession();
  try { window.localStorage.clear(); } catch { /* none */ }
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  authState.current = { status: "out", clientId: "cid", user: null };
});

const draw = async (node: React.ReactNode) => {
  await act(async () => { root.render(node); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
};

describe("looks", () => {
  it("reads a look it can draw and falls back to the default otherwise", () => {
    expect(DEFAULT_LOOK).toBe("tractor/red");
    expect(parseLook("tractor/jade")).toEqual({ kind: "tractor", colour: "jade" });
    for (const raw of [null, undefined, "", "goat/jade", "tractor/mauve", "tractor/red/x", 7]) {
      expect(parseLook(raw)).toEqual({ kind: "tractor", colour: "red" });
    }
  });

  it("every colour has a palette entry and every earned colour a rule", () => {
    expect(COMPANIONS.tractor).toEqual(Object.keys(TRACTOR_COLOURS));
    expect(COMPANIONS.tractor.slice(0, 3)).toEqual(["red", "green", "blue"]);
    for (const id of Object.keys(LOOK_UNLOCKS)) expect(COMPANIONS.tractor).toContain(id.split("/")[1]);
  });

  it("unlocks by count, keeps the equipped one, and prefers the server's word", () => {
    const at = (rounds: number, wins: number, equipped = DEFAULT_LOOK) =>
      lookCatalogue({ rounds, ranked_wins: wins }, equipped).filter((e) => e.unlocked).map((e) => e.id);
    expect(at(0, 0)).toEqual(["tractor/red", "tractor/green", "tractor/blue"]);
    expect(at(25, 0)).toEqual(["tractor/red", "tractor/green", "tractor/blue", "tractor/yellow", "tractor/orange"]);
    expect(at(0, 1)).toContain("tractor/ink");
    expect(at(0, 0, "tractor/jade")).toContain("tractor/jade");
    const served = lookCatalogue({}, DEFAULT_LOOK, [{ id: "tractor/porcelain", unlocked: true, needs: { count: "rounds", of: 100 } }]);
    expect(served.find((e) => e.id === "tractor/porcelain")?.unlocked).toBe(true);
  });

  it("the drawing parses back to elements, never raw HTML", () => {
    const nodes = parseArt(tractorMarkup("porcelain", "t"));
    expect(nodes[0][0]).toBe("defs");
    const body = nodes.find((n) => n[1].class === "cmp-body")!;
    expect(body[2].filter((n) => n[1].class === "cmp-eye")).toHaveLength(2);
  });
});

describe("the figure and the portrait", () => {
  it("draws a person's portrait from their look and a bot's initial", async () => {
    await draw(<>
      <Portrait look="tractor/orange" size={28} />
      <Portrait look={null} size={28} />
      <Portrait look="tractor/orange" bot initial="Bot 2" size={28} />
    </>);
    const [orange, plain] = [...host.querySelectorAll("img.portrait")];
    expect(orange.getAttribute("data-look")).toBe("tractor/orange");
    expect(orange.getAttribute("src")).toMatch(/^data:image\/svg\+xml/);
    expect(plain.getAttribute("data-look")).toBe("tractor/red");
    expect(host.querySelector(".portrait-bot")?.textContent).toBe("B");
    expect(host.querySelectorAll("img")).toHaveLength(2);
  });

  it("each pose is a class on the one drawing; sleep closes the eyes and adds the z", async () => {
    for (const pose of ["idle", "hop", "cheer", "sleep"] as const) {
      await draw(<Companion colour="red" size={160} state={pose} />);
      const svg = host.querySelector("svg.cmp")!;
      expect(svg.classList.contains(`cmp-${pose}`)).toBe(true);
      expect(svg.querySelectorAll(".cmp-eye")).toHaveLength(pose === "sleep" ? 0 : 2);
      expect(svg.querySelector(".cmp-z") !== null).toBe(pose === "sleep");
    }
  });

  it("a one-shot pose ends when its body animation ends", async () => {
    const end = vi.fn();
    await draw(<Companion colour="red" size={160} state="hop" onPoseEnd={end} />);
    const body = host.querySelector(".cmp-body")!;
    // React names the event by what the environment supports
    const name = "AnimationEvent" in window ? "animationend" : "webkitAnimationEnd";
    act(() => { body.dispatchEvent(new Event(name, { bubbles: true })); });
    expect(end).toHaveBeenCalledTimes(1);
  });
});

describe("the gold dot", () => {
  const looks = (unlocked: string[]) => COMPANIONS.tractor.map((c) => ({
    id: `tractor/${c}`, unlocked: unlocked.includes(c), needs: null,
  }));
  it("stays off for what an account starts with and lights for a new unlock until seen", () => {
    expect(hasNewLook("a", looks(["red", "green", "blue"]))).toBe(false);
    markLooksSeen("a", looks(["red", "green", "blue"]), true);
    expect(hasNewLook("a", looks(["red", "green", "blue"]))).toBe(false);
    expect(hasNewLook("a", looks(["red", "green", "blue", "yellow"]))).toBe(true);
    markLooksSeen("a", looks(["red", "green", "blue", "yellow"]));
    expect(hasNewLook("a", looks(["red", "green", "blue", "yellow"]))).toBe(false);
  });
});

describe("the Collection tab", () => {
  const user: AuthUser = {
    name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry",
    rounds_played: 14, ranked_wins: 0, look: "tractor/red", companions: "team", features: { collection: true },
  };
  const fetches: { url: string; init?: RequestInit }[] = [];
  beforeEach(() => {
    fetches.length = 0;
    globalThis.fetch = vi.fn(async (url: string, init?: RequestInit) => {
      fetches.push({ url, init });
      if (url.includes("/api/leaderboard")) {
        return { status: 200, json: async () => ({ period: "all", players: [], anchor: { name: "x", rating: 1 }, anchors: {},
          me: { rank: 4, name: "Jerry", rating: 930, rounds: 14, levels_per_round: 0.3, week_rank_move: null, provisional: false,
                you: true, look: "tractor/red" } }) } as Response;
      }
      const body = JSON.parse(String(init?.body ?? "{}"));
      return { status: 200, json: async () => ({ ...user, ...body }) } as Response;
    }) as unknown as typeof fetch;
  });

  it("shows the Tractor on the felt, your row as others see it, the colours and the one control", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw(<CollectionPage />);
    expect(host.querySelector(".large-title")?.textContent).toBe("Collection");
    expect(host.querySelector(".coll-felt svg.cmp.cmp-idle")).not.toBeNull();
    const row = host.querySelector(".coll-row .lb-row")!;
    expect(row.classList.contains("me")).toBe(false);
    expect(row.textContent).toBe("4Jerry930");
    const swatches = [...host.querySelectorAll<HTMLButtonElement>(".coll-swatch")];
    expect(swatches).toHaveLength(COMPANIONS.tractor.length);
    expect(swatches.filter((s) => s.classList.contains("locked")).map((s) => s.getAttribute("aria-label"))).toEqual([
      "Lantern orange, 14 of 25 rounds", "Jade, 14 of 50 rounds", "Blue and white, 14 of 100 rounds", "Ink black, A ranked win",
    ]);
    expect(swatches[0].getAttribute("aria-checked")).toBe("true");
    expect(host.querySelector(".coll-status")?.textContent).toBe("");
    expect([...host.querySelectorAll(".coll-mode .segmented-btn")].map((b) => b.textContent)).toEqual(["Team", "Individual", "Off"]);
    // no visible words under the swatches: the count is the felt's one status line
    expect(host.querySelector(".coll-swatches")?.textContent).toBe("");
  });

  it("a locked colour is shown with its count; an unlocked one is equipped", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw(<CollectionPage />);
    const swatch = (name: string) => [...host.querySelectorAll<HTMLButtonElement>(".coll-swatch")]
      .find((s) => s.getAttribute("aria-label")!.startsWith(name))!;
    await act(async () => { swatch("Lantern orange").click(); });
    expect(host.querySelector(".coll-status")?.textContent).toBe("14 of 25 rounds");
    expect(fetches.some((f) => f.url === "/api/me/look")).toBe(false);
    await act(async () => { swatch("Imperial yellow").click(); await new Promise((r) => setTimeout(r, 0)); });
    const put = fetches.find((f) => f.url === "/api/me/look")!;
    expect(put.init?.method).toBe("PUT");
    expect(JSON.parse(String(put.init?.body))).toEqual({ look: "tractor/yellow" });
    expect(updated).toHaveBeenCalledWith(expect.objectContaining({ look: "tractor/yellow" }));
    expect(host.querySelector(".coll-status")?.textContent).toBe("");
  });

  it("a guest's choice of where companions show stays on the device", async () => {
    await draw(<CollectionPage />);
    expect(host.querySelector(".coll-row")).toBeNull();
    const off = [...host.querySelectorAll<HTMLButtonElement>(".coll-mode .segmented-btn")].find((b) => b.textContent === "Off")!;
    await act(async () => { off.click(); });
    expect(off.getAttribute("aria-pressed")).toBe("true");
    expect(window.localStorage.getItem("shengji.companions")).toBe("off");
    expect(fetches.some((f) => f.url === "/api/me/look")).toBe(false);
  });
});

describe("other viewers", () => {
  const row = { rank: 2, name: "Mei", rating: 950, rounds: 30, levels_per_round: 0.4, week_rank_move: null,
                provisional: false, you: false, look: "tractor/jade" };
  it("a leaderboard row shows the initial unless the Collection is shown to this viewer", async () => {
    authState.current = { status: "in", clientId: "cid", user: { name: "A", email: "a@x", picture: null, display_name: null, name_shown: "A" } };
    await draw(<ul><Row row={row} /></ul>);
    expect(host.querySelector(".lb-row .avatar")?.textContent).toBe("M");
    expect(host.querySelector(".portrait")).toBeNull();
    authState.current = { status: "in", clientId: "cid", user: { name: "A", email: "a@x", picture: null, display_name: null, name_shown: "A",
                                                                 features: { collection: true } } };
    await draw(<ul><Row row={{ ...row }} /></ul>);
    expect(host.querySelector(".lb-row .portrait")?.getAttribute("data-look")).toBe("tractor/jade");
    authState.current = { status: "out", clientId: "cid", user: null, collection: true };
    await draw(<ul><Row row={{ ...row, look: "tractor/ink" }} /></ul>);
    expect(host.querySelector(".lb-row .portrait")?.getAttribute("data-look")).toBe("tractor/ink");
  });
});

describe("entitlements and writes stay with their session and their order", () => {
  type Reply = { status: number; body: unknown };
  const base: AuthUser = {
    name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry",
    rounds_played: 9, ranked_wins: 0, look: "tractor/red", companions: "team", features: { collection: true },
  };
  let me: AuthUser;
  let held: { url: string; body: unknown; reply: (r: Reply) => void }[];
  let holdPuts: boolean;
  beforeEach(() => {
    me = { ...base };
    held = [];
    holdPuts = false;
    updated.mockImplementation((u: AuthUser) => { authState.current = { ...authState.current, user: u }; });
    globalThis.fetch = vi.fn((url: string, init?: RequestInit) => {
      const answer = (r: Reply) => ({ status: r.status, json: async () => r.body }) as Response;
      if (url.includes("/api/leaderboard")) return Promise.resolve(answer({ status: 200, body: { period: "all", players: [], me: null, anchor: { name: "x", rating: 1 }, anchors: {} } }));
      if (url === "/api/me") return Promise.resolve(answer({ status: 200, body: me }));
      const body = JSON.parse(String(init?.body ?? "{}"));
      if (holdPuts) return new Promise<Response>((res) => held.push({ url, body, reply: (r) => res(answer(r)) }));
      return Promise.resolve(answer({ status: 200, body: { ...me, ...body } }));
    }) as unknown as typeof fetch;
    authState.current = { status: "in", clientId: "cid", user: { ...base } };
  });
  afterEach(() => updated.mockReset());

  const swatch = (name: string) => [...host.querySelectorAll<HTMLButtonElement>(".coll-swatch")]
    .find((s) => s.getAttribute("aria-label")!.startsWith(name))!;
  const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

  it("a tenth round earned while signed in unlocks yellow without a reload", async () => {
    await draw(<CollectionPage />);
    expect(swatch("Imperial yellow").classList.contains("locked")).toBe(true);
    // the round ends elsewhere: the server now counts ten
    me = { ...base, rounds_played: 10 };
    await act(async () => { swatch("Imperial yellow").click(); });
    await flush();
    await draw(<CollectionPage />);
    expect(swatch("Imperial yellow").classList.contains("locked")).toBe(false);
    expect(updated).toHaveBeenCalledWith(expect.objectContaining({ rounds_played: 10 }));
    // the locked tap rechecked and, now unlocked, equipped it
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.some(([u, i]) =>
      u === "/api/me/look" && JSON.parse(String((i as RequestInit).body)).look === "tractor/yellow")).toBe(true);
  });

  it("opening the Collection reads the account's counts again", async () => {
    me = { ...base, rounds_played: 10 };
    await draw(<CollectionPage />);
    await flush();
    expect(updated).toHaveBeenCalledWith(expect.objectContaining({ rounds_played: 10 }));
  });

  it("a save that lands after a switch to another account changes nothing", async () => {
    await draw(<CollectionPage />);
    await flush();
    updated.mockClear();
    holdPuts = true;
    await act(async () => { swatch("Paddy green").click(); });
    expect(held).toHaveLength(1);
    // account B signs in while A's save is in flight
    act(() => { forgetPrivateSession(); });
    authState.current = { status: "in", clientId: "cid", user: { ...base, name: "Bo", email: "b@x", name_shown: "Bo" } };
    await act(async () => { held[0].reply({ status: 200, body: { ...base, look: "tractor/green" } }); });
    await flush();
    expect(updated).not.toHaveBeenCalled();
    // and a failed save from A does not roll B back either
    holdPuts = true;
    authState.current = { status: "in", clientId: "cid", user: { ...base } };
    await draw(<CollectionPage />);
    await flush();
    updated.mockClear();
    await act(async () => { swatch("Enamel blue").click(); });
    act(() => { forgetPrivateSession(); });
    await act(async () => { held[1].reply({ status: 500, body: {} }); });
    await flush();
    expect(updated).not.toHaveBeenCalled();
  });

  it("consecutive mode changes that complete out of order leave the last one", async () => {
    await draw(<CollectionPage />);
    await flush();
    holdPuts = true;
    const mode = (t: string) => [...host.querySelectorAll<HTMLButtonElement>(".coll-mode .segmented-btn")].find((b) => b.textContent === t)!;
    await act(async () => { mode("Individual").click(); });
    await draw(<CollectionPage />);
    await act(async () => { mode("Off").click(); });
    expect(held.map((h) => h.body)).toEqual([{ companions: "individual" }, { companions: "off" }]);
    await act(async () => { held[1].reply({ status: 200, body: { ...base, companions: "off" } }); });
    await act(async () => { held[0].reply({ status: 200, body: { ...base, companions: "individual" } }); });
    await flush();
    expect(authState.current.user?.companions).toBe("off");
    // an earlier write failing after a later one landed does not roll it back
    await act(async () => { mode("Team").click(); });
    await draw(<CollectionPage />);
    await act(async () => { mode("Individual").click(); });
    await act(async () => { held[3].reply({ status: 200, body: { ...base, companions: "individual" } }); });
    await act(async () => { held[2].reply({ status: 500, body: {} }); });
    await flush();
    expect(authState.current.user?.companions).toBe("individual");
  });
});
