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
  // the server's copy of the account: a write changes it when it is answered with 200
  let server: AuthUser;
  let held: { url: string; body: Record<string, unknown>; reply: (status?: number) => void }[];
  let holdPuts: boolean;
  let holdGets: boolean;
  beforeEach(() => {
    server = { ...base };
    held = [];
    holdPuts = false;
    holdGets = false;
    updated.mockImplementation((u: AuthUser) => { authState.current = { ...authState.current, user: u }; });
    const answer = (r: Reply) => ({ status: r.status, json: async () => r.body }) as Response;
    globalThis.fetch = vi.fn((url: string, init?: RequestInit) => {
      if (url.includes("/api/leaderboard")) return Promise.resolve(answer({ status: 200, body: { period: "all", players: [], me: null, anchor: { name: "x", rating: 1 }, anchors: {} } }));
      if (url === "/api/me") {
        const snapshot = { ...server };
        if (!holdGets) return Promise.resolve(answer({ status: 200, body: snapshot }));
        return new Promise<Response>((res) => held.push({ url, body: {}, reply: () => res(answer({ status: 200, body: snapshot })) }));
      }
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      const apply = (status = 200) => {
        if (status === 200) server = { ...server, ...body } as AuthUser;
        return answer({ status, body: status === 200 ? { ...server } : {} });
      };
      if (!holdPuts) return Promise.resolve(apply());
      return new Promise<Response>((res) => held.push({ url, body, reply: (status) => res(apply(status)) }));
    }) as unknown as typeof fetch;
    authState.current = { status: "in", clientId: "cid", user: { ...base } };
  });
  afterEach(() => updated.mockReset());

  const swatch = (name: string) => [...host.querySelectorAll<HTMLButtonElement>(".coll-swatch")]
    .find((s) => s.getAttribute("aria-label")!.startsWith(name))!;
  const mode = (t: string) => [...host.querySelectorAll<HTMLButtonElement>(".coll-mode .segmented-btn")].find((b) => b.textContent === t)!;
  const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  const puts = () => held.filter((h) => h.url === "/api/me/look");
  const gets = () => held.filter((h) => h.url === "/api/me");
  const shownLook = () => host.querySelector(".coll-swatch.on")?.getAttribute("aria-label");
  const reload = async () => {
    holdGets = false;
    const { refreshAccount } = await import("./writes");
    await act(async () => { await refreshAccount(); });
  };

  it("a tenth round earned while signed in unlocks yellow without a reload", async () => {
    await draw(<CollectionPage />);
    expect(swatch("Imperial yellow").classList.contains("locked")).toBe(true);
    server = { ...base, rounds_played: 10 };
    await act(async () => { swatch("Imperial yellow").click(); });
    await flush();
    await draw(<CollectionPage />);
    expect(swatch("Imperial yellow").classList.contains("locked")).toBe(false);
    expect(server.look).toBe("tractor/yellow");
    expect(authState.current.user?.look).toBe("tractor/yellow");
  });

  it("opening the Collection reads the account's counts again", async () => {
    server = { ...base, rounds_played: 10 };
    await draw(<CollectionPage />);
    await flush();
    expect(updated).toHaveBeenCalledWith(expect.objectContaining({ rounds_played: 10 }));
  });

  for (const order of ["the read answers last", "the read answers first"] as const) {
    it(`a read started before a choice never undoes it (${order})`, async () => {
      holdGets = true;
      holdPuts = true;
      await draw(<CollectionPage />);           // the open's read starts, with red
      expect(gets()).toHaveLength(1);
      await act(async () => { swatch("Paddy green").click(); });
      await draw(<CollectionPage />);
      const put = puts()[0];
      if (order === "the read answers last") {
        await act(async () => { put.reply(); });
        await flush();
        await act(async () => { gets()[0].reply(); });
      } else {
        await act(async () => { gets()[0].reply(); });
        await flush();
        await act(async () => { put.reply(); });
      }
      await flush();
      await draw(<CollectionPage />);
      expect(authState.current.user?.look).toBe("tractor/green");
      expect(shownLook()).toBe("Paddy green");
      await reload();
      expect(authState.current.user?.look).toBe("tractor/green");
    });
  }

  for (const first of [200, 500] as const) {
    it(`rapid mode changes end at the last choice on the server and the screen (first answer ${first})`, async () => {
      await draw(<CollectionPage />);
      await flush();
      holdPuts = true;
      await act(async () => { mode("Individual").click(); });
      await draw(<CollectionPage />);
      await act(async () => { mode("Off").click(); });
      await draw(<CollectionPage />);
      await act(async () => { mode("Team").click(); });
      await draw(<CollectionPage />);
      await act(async () => { mode("Off").click(); });
      // one write on the wire; the latest choice waits for it
      expect(puts().map((h) => h.body)).toEqual([{ companions: "individual" }]);
      expect(authState.current.user?.companions).toBe("off");
      await act(async () => { puts()[0].reply(first); });
      await flush();
      expect(authState.current.user?.companions).toBe("off");    // a late answer for an older choice shows nothing
      expect(puts().map((h) => h.body)).toEqual([{ companions: "individual" }, { companions: "off" }]);
      await act(async () => { puts()[1].reply(); });
      await flush();
      expect(server.companions).toBe("off");
      expect(authState.current.user?.companions).toBe("off");
      // a failed change rolls back to the last confirmed choice, not an older one
      await draw(<CollectionPage />);
      await act(async () => { mode("Team").click(); });
      expect(authState.current.user?.companions).toBe("team");
      await act(async () => { puts()[2].reply(500); });
      await flush();
      expect(authState.current.user?.companions).toBe("off");
      await reload();
      expect(authState.current.user?.companions).toBe("off");
      expect(server.companions).toBe("off");
    });
  }

  it("a save that lands after a switch to another account changes nothing", async () => {
    await draw(<CollectionPage />);
    await flush();
    updated.mockClear();
    holdPuts = true;
    await act(async () => { swatch("Paddy green").click(); });
    expect(puts()).toHaveLength(1);
    updated.mockClear();
    act(() => { forgetPrivateSession(); });
    authState.current = { status: "in", clientId: "cid", user: { ...base, name: "Bo", email: "b@x", name_shown: "Bo" } };
    await act(async () => { puts()[0].reply(); });
    await flush();
    expect(updated).not.toHaveBeenCalled();
    expect(authState.current.user?.name).toBe("Bo");
    expect(authState.current.user?.look).toBe("tractor/red");
    // and B's own choice is sent at once, not queued behind A's
    await draw(<CollectionPage />);
    await flush();
    await act(async () => { swatch("Enamel blue").click(); });
    expect(puts().map((h) => h.body)).toEqual([{ look: "tractor/green" }, { look: "tractor/blue" }]);
    act(() => { forgetPrivateSession(); });
    updated.mockClear();
    await act(async () => { puts()[1].reply(500); });
    await flush();
    expect(updated).not.toHaveBeenCalled();
  });
});
