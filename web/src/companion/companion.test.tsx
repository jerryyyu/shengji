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
  // a character page opened by an earlier test is its own address: start on the grid
  window.history.replaceState(null, "", "/");
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
// the Collection opens on its grid; a tap on the ticked tile (the one in use) opens its page
const drawOpen = async () => {
  await draw(<CollectionPage />);
  const worn = [...host.querySelectorAll<HTMLButtonElement>(".coll-yours .coll-tile")].find((b) => b.querySelector(".coll-tick"));
  if (worn && !host.querySelector(".char-page")) {
    await act(async () => { worn.click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  }
};

describe("looks", () => {
  it("reads a look it can draw and falls back to the default otherwise", () => {
    expect(DEFAULT_LOOK).toBe("tractor/red");
    expect(parseLook("tractor/jade")).toEqual({ kind: "tractor", colour: "jade" });
    expect(parseLook("lamb/jade")).toEqual({ kind: "lamb", colour: "jade" });
    for (const raw of [null, undefined, "", "lamb/mauve", "goat/jade", "panda/bamboo", "dragon/jade", "tractor/mauve", "tractor/red/x", 7]) {
      expect(parseLook(raw)).toEqual({ kind: "tractor", colour: "red" });
    }
  });

  it("every colour has a palette entry and every earned colour a rule", () => {
    expect(COMPANIONS.tractor).toEqual(Object.keys(TRACTOR_COLOURS));
    expect(COMPANIONS.tractor.slice(0, 3)).toEqual(["red", "green", "blue"]);
    for (const id of Object.keys(LOOK_UNLOCKS)) expect(COMPANIONS.tractor).toContain(id.split("/")[1]);
  });

  it("unlocks by count, keeps the equipped one, and prefers the server's word", () => {
    const at = (wins: number, equipped = DEFAULT_LOOK) =>
      lookCatalogue({ rounds: 5000, ranked_wins: wins, ranked_games: 500 }, equipped)
        .filter((e) => e.unlocked && e.id.startsWith("tractor/")).map((e) => e.id);
    // rounds played and games won unlock nothing: ranked rounds won do
    expect(at(0)).toEqual(["tractor/red", "tractor/green", "tractor/blue"]);
    expect(at(25)).toEqual(["tractor/red", "tractor/green", "tractor/blue", "tractor/yellow", "tractor/orange"]);
    expect(at(99)).not.toContain("tractor/porcelain");
    expect(at(100)).toContain("tractor/porcelain");
    expect(at(999)).not.toContain("tractor/ink");
    expect(at(1000)).toContain("tractor/ink");
    // a colour in use stays unlocked though its count falls short
    expect(at(0, "tractor/jade")).toContain("tractor/jade");
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
    rounds_played: 14, ranked_wins: 14, ranked_games: 0, look: "tractor/red", companions: "team", features: { collection: true },
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

  const swatch = (name: string) => [...host.querySelectorAll<HTMLButtonElement>(".coll-swatch")]
    .find((s) => s.getAttribute("aria-label")!.startsWith(name))!;

  it("shows the Tractor on the felt, the companions, its colours, the one status line, the button and the switch", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await drawOpen();
    expect(host.querySelector(".large-title")?.textContent).toBe("Tractor");
    expect(host.querySelector(".coll-felt svg.cmp.cmp-idle")).not.toBeNull();
    const swatches = [...host.querySelectorAll<HTMLButtonElement>(".coll-swatch")];
    expect(swatches).toHaveLength(COMPANIONS.tractor.length);
    expect(swatches.filter((s) => s.classList.contains("locked")).map((s) => s.getAttribute("aria-label"))).toEqual([
      "Lantern orange, 14 of 25 ranked rounds", "Jade, 14 of 50 ranked rounds", "Blue and white, 14 of 100 ranked rounds",
      "Ink black, 14 of 1,000 ranked rounds",
    ]);
    expect(swatches[0].getAttribute("aria-checked")).toBe("true");
    expect(host.querySelector(".coll-status")?.textContent).toBe("Tractor · Icon red");
    expect(host.querySelector(".coll-use")?.textContent).toBe("In use");
    // no visible words on the swatches
    expect(host.querySelector(".coll-swatches")?.textContent).toBe("");
    // the switch is on the grid
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-back")!.click(); });
    expect(host.querySelector(".coll-at-table")?.textContent).toBe("Show at the table");
  });

  it("a locked colour's button names what unlocks it; an unlocked one is put in use by Use", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await drawOpen();
    await act(async () => { swatch("Lantern orange").click(); });
    expect(host.querySelector(".coll-use")?.textContent).toBe("Win 25 ranked rounds to unlock · 14 of 25");
    expect(fetches.some((f) => f.url === "/api/me/look")).toBe(false);
    await act(async () => { swatch("Imperial yellow").click(); });
    expect(fetches.some((f) => f.url === "/api/me/look")).toBe(false);
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-use")!.click(); await new Promise((r) => setTimeout(r, 0)); });
    const put = fetches.find((f) => f.url === "/api/me/look")!;
    expect(put.init?.method).toBe("PUT");
    expect(JSON.parse(String(put.init?.body))).toEqual({ look: "tractor/yellow" });
    expect(updated).toHaveBeenCalledWith(expect.objectContaining({ look: "tractor/yellow" }));
  });

  it("45 ranked rounds won and no game won unlock yellow and orange, and jade reads 45 of 50", async () => {
    authState.current = { status: "in", clientId: "cid", user: { ...user, rounds_played: 60, ranked_wins: 45, ranked_games: 0 } };
    await drawOpen();
    const locked = [...host.querySelectorAll<HTMLButtonElement>(".coll-swatch.locked")].map((s) => s.getAttribute("aria-label"));
    expect(locked).toEqual(["Jade, 45 of 50 ranked rounds", "Blue and white, 45 of 100 ranked rounds", "Ink black, 45 of 1,000 ranked rounds"]);
    expect(swatch("Imperial yellow").classList.contains("locked")).toBe(false);
    expect(swatch("Lantern orange").classList.contains("locked")).toBe(false);
    await act(async () => { swatch("Jade").click(); });
    expect(host.querySelector(".coll-use")?.textContent).toBe("Win 50 ranked rounds to unlock · 45 of 50");
  });

  it("a guest's Show at the table stays on the device", async () => {
    await draw(<CollectionPage />);
    const sw = host.querySelector<HTMLButtonElement>(".coll-at-table")!;
    await act(async () => { sw.click(); });
    expect(sw.getAttribute("aria-checked")).toBe("false");
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
    forgetPrivateSession();          // each test is its own session: an earlier test's held writes settle
  });
  afterEach(() => updated.mockReset());

  const swatch = (name: string) => [...host.querySelectorAll<HTMLButtonElement>(".coll-swatch")]
    .find((s) => s.getAttribute("aria-label")!.startsWith(name))!;
  // a colour is put in use by its swatch, then Use
  const pick = async (name: string) => {
    await act(async () => { swatch(name).click(); });
    const use = host.querySelector<HTMLButtonElement>(".coll-use");
    if (use && !use.disabled) await act(async () => { use.click(); });
  };
  const toggle = () => host.querySelector<HTMLButtonElement>(".coll-at-table")!;
  const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  const puts = () => held.filter((h) => h.url === "/api/me/look");
  const gets = () => held.filter((h) => h.url === "/api/me");
  const shownLook = () => host.querySelector(".coll-swatch.on")?.getAttribute("aria-label");
  const reload = async () => {
    holdGets = false;
    const { refreshAccount } = await import("./writes");
    await act(async () => { await refreshAccount(); });
  };

  it("a tenth ranked round won while signed in unlocks yellow without a reload", async () => {
    await drawOpen();
    await flush();
    expect(swatch("Imperial yellow").classList.contains("locked")).toBe(true);
    server = { ...base, ranked_wins: 10 };
    const { refreshAccount } = await import("./writes");
    await act(async () => { await refreshAccount(); });
    await drawOpen();
    expect(swatch("Imperial yellow").classList.contains("locked")).toBe(false);
    await pick("Imperial yellow");
    await flush();
    expect(server.look).toBe("tractor/yellow");
    expect(authState.current.user?.look).toBe("tractor/yellow");
  });

  it("opening the Collection reads the account's counts again", async () => {
    server = { ...base, rounds_played: 10 };
    await drawOpen();
    await flush();
    expect(updated).toHaveBeenCalledWith(expect.objectContaining({ rounds_played: 10 }));
  });

  for (const order of ["the read answers last", "the read answers first"] as const) {
    it(`a read started before a choice never undoes it (${order})`, async () => {
      holdGets = true;
      holdPuts = true;
      await drawOpen();           // the open's read starts, with red
      expect(gets()).toHaveLength(1);
      await pick("Paddy green");
      await drawOpen();
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
      await drawOpen();
      expect(authState.current.user?.look).toBe("tractor/green");
      expect(shownLook()).toBe("Paddy green");
      await reload();
      expect(authState.current.user?.look).toBe("tractor/green");
    });
  }

  for (const first of [200, 500] as const) {
    it(`rapid mode changes end at the last choice on the server and the screen (first answer ${first})`, async () => {
      server = { ...base, companions: "off" };
      authState.current = { status: "in", clientId: "cid", user: { ...base, companions: "off" } };
      await draw(<CollectionPage />);
      await flush();
      holdPuts = true;
      await act(async () => { toggle().click(); });     // on
      await draw(<CollectionPage />);
      await act(async () => { toggle().click(); });     // off
      await draw(<CollectionPage />);
      await act(async () => { toggle().click(); });     // on
      await draw(<CollectionPage />);
      await act(async () => { toggle().click(); });     // off
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
      await act(async () => { toggle().click(); });
      expect(authState.current.user?.companions).toBe("individual");
      await act(async () => { puts()[2].reply(500); });
      await flush();
      expect(authState.current.user?.companions).toBe("off");
      await reload();
      expect(authState.current.user?.companions).toBe("off");
      expect(server.companions).toBe("off");
    });
  }

  it("a read started while a write is on the wire never undoes the confirmed choice", async () => {
    await drawOpen();
    await flush();
    holdPuts = true;
    holdGets = true;
    await pick("Paddy green");
    const { refreshAccount } = await import("./writes");
    let read: Promise<unknown> = Promise.resolve();
    await act(async () => { read = refreshAccount(); });          // captures red
    await act(async () => { puts()[0].reply(); });               // the server now holds green
    await flush();
    await act(async () => { gets()[gets().length - 1].reply(); await read; });
    await flush();
    expect(server.look).toBe("tractor/green");
    expect(authState.current.user?.look).toBe("tractor/green");
  });

  it("an older read answering after a newer one never puts its counts back", async () => {
    await drawOpen();
    await flush();
    holdGets = true;
    const { refreshAccount } = await import("./writes");
    let older: Promise<unknown> = Promise.resolve();
    let newer: Promise<unknown> = Promise.resolve();
    await act(async () => { older = refreshAccount(); });         // sees 9 rounds
    server = { ...server, rounds_played: 10 };
    await act(async () => { newer = refreshAccount(); });         // sees 10
    const [a, b] = gets().slice(-2);
    await act(async () => { b.reply(); await newer; });
    expect(authState.current.user?.rounds_played).toBe(10);
    await act(async () => { a.reply(); await older; });
    expect(authState.current.user?.rounds_played).toBe(10);
  });

  it("a session change settles the writes still waiting to be sent", async () => {
    await drawOpen();
    await flush();
    holdPuts = true;
    const { writeMode } = await import("./writes");
    let first: Promise<void> = Promise.resolve();
    let second: Promise<void> = Promise.resolve();
    await act(async () => { first = writeMode("individual"); });
    await act(async () => { second = writeMode("off"); });        // waits behind the first
    expect(puts()).toHaveLength(1);
    act(() => { forgetPrivateSession(); });
    const settled = (p: Promise<unknown>) => Promise.race([p.then(() => "settled", () => "settled"),
      new Promise((r) => setTimeout(() => r("pending"), 20))]);
    await act(async () => { void writeMode("team").catch(() => {}); });    // the new session's first write
    expect(await settled(second)).toBe("settled");
    await act(async () => { puts()[0].reply(); });
    expect(await settled(first)).toBe("settled");
    // the old session's waiting choice was never sent
    expect(puts().map((h) => h.body)).toEqual([{ companions: "individual" }, { companions: "team" }]);
  });

  it("an unlock read for an older tap never saves over a newer choice", async () => {
    await drawOpen();
    await flush();
    server = { ...server, ranked_wins: 10 };        // the client still shows none
    holdGets = true;
    const { equip } = await import("./writes");
    await act(async () => { void equip("tractor/yellow", false); });   // locked here: reads first
    const unlockRead = gets()[gets().length - 1];
    holdGets = false;
    await pick("Paddy green");                                         // a newer choice, saved at once
    await flush();
    expect(server.look).toBe("tractor/green");
    await act(async () => { unlockRead.reply(); });
    await flush();
    expect(server.look).toBe("tractor/green");
    expect(authState.current.user?.look).toBe("tractor/green");
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([u, i]) =>
      u === "/api/me/look" && String((i as RequestInit).body).includes("yellow"))).toHaveLength(0);
  });

  it("re-tapping the equipped colour also overtakes an older tap's unlock read", async () => {
    await drawOpen();
    await flush();
    server = { ...server, ranked_wins: 10 };
    holdGets = true;
    const { equip } = await import("./writes");
    await act(async () => { void equip("tractor/yellow", false); });
    const unlockRead = gets()[gets().length - 1];
    await act(async () => { swatch("Icon red").click(); });           // the one in use
    await act(async () => { unlockRead.reply(); });
    await flush();
    expect(server.look).toBe("tractor/red");
    expect(authState.current.user?.look).toBe("tractor/red");
  });

  it("signing out settles a queued write with no further Collection call", async () => {
    await drawOpen();
    await flush();
    holdPuts = true;
    const { writeMode } = await import("./writes");
    let first: Promise<void> = Promise.resolve();
    let second: Promise<void> = Promise.resolve();
    await act(async () => { first = writeMode("individual"); });
    await act(async () => { second = writeMode("off"); });
    act(() => { forgetPrivateSession(); });                          // the session ends; nothing else is called
    const settled = (p: Promise<unknown>) => Promise.race([p.then(() => "settled", () => "settled"),
      new Promise((r) => setTimeout(() => r("pending"), 20))]);
    expect(await settled(second)).toBe("settled");
    await act(async () => { puts()[0].reply(); });
    await flush();
    expect(await settled(first)).toBe("settled");
    expect(puts().map((h) => h.body)).toEqual([{ companions: "individual" }]);
  });

  it("a save that lands after a switch to another account changes nothing", async () => {
    await drawOpen();
    await flush();
    updated.mockClear();
    holdPuts = true;
    await pick("Paddy green");
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
    await drawOpen();
    await flush();
    await pick("Enamel blue");
    expect(puts().map((h) => h.body)).toEqual([{ look: "tractor/green" }, { look: "tractor/blue" }]);
    act(() => { forgetPrivateSession(); });
    updated.mockClear();
    await act(async () => { puts()[1].reply(500); });
    await flush();
    expect(updated).not.toHaveBeenCalled();
  });
});
