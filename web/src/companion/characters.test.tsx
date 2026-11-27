// The free companions (the Bun, the Chick, the Sparrow) beside the Tractor
// and its rider: every look parses and draws, a team marks its figures by
// pad shape and scarf, a team's level grows its figures to the seat cap and
// only a gain pops, the character page's foot follows ownership, and the
// table draws people's companions in their team's corner in Team view only.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthState, AuthUser } from "../auth";
import type { GameState, StatePlayer } from "../protocol";

const { authState } = vi.hoisted(() => ({
  authState: { current: { status: "out", clientId: "cid", user: null } as AuthState },
}));
vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));
vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return { ...real, useAuth: () => authState.current, auth: { updated: () => {}, get state() { return authState.current; } } };
});

import { Companion } from "./Companion";
import { DRAWINGS } from "./kinds";
import { COMPANIONS, COMPANION_KINDS, FREE_KINDS, lookCatalogue, parseLook } from "./look";
import { companionSize } from "./rig";
import { parseArt } from "./Tractor";
import TableCompanions, { LEVEL_UP_MS, MOVES, SEAT_SIZE, TAP_WALK_MS, around, levelIndex } from "./TableCompanions";
import { hasNewLook } from "./seen";
import type { LookEntry } from "./look";
import { HAND_LIFT, LIFT, clear, figureBox, meets, pathClear, zonesFor } from "./seatZones";
import type { Layout, Rect, SeatPos } from "./seatZones";
import { TABLES } from "./seatZones.fixtures";
import CollectionPage from "../components/CollectionPage";
import { forgetHomeSession } from "../home/session";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  // a character page opened by an earlier test is its own address: start on the grid
  window.history.replaceState(null, "", "/");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
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

describe("the free companions", () => {
  it("are the Tractor, the Bun, the Chick and the Sparrow, four colours each beside the Tractor's eight", () => {
    expect(FREE_KINDS).toEqual(["tractor", "bun", "chick", "sparrow"]);
    expect(COMPANION_KINDS).toEqual(["tractor", "bun", "chick", "sparrow", "lamb", "panda"]);
    expect(COMPANIONS.bun).toEqual(["plain", "custard", "taro", "peach"]);
    expect(COMPANIONS.chick).toEqual(["yellow", "cream", "cocoa", "ink"]);
    expect(COMPANIONS.sparrow).toEqual(["tree", "java", "snow", "oriole"]);
    expect(parseLook("chick/ink")).toEqual({ kind: "chick", colour: "ink" });
    // a colour of another companion, or one not drawn here, is the default
    for (const bad of ["bun/red", "sparrow/plain", "goat/newyear", "chick/ink/x"]) {
      expect(parseLook(bad)).toEqual({ kind: "tractor", colour: "red" });
    }
    const fresh = lookCatalogue({ rounds: 0, ranked_wins: 0 }, "tractor/red");
    for (const kind of ["bun", "chick", "sparrow"]) {
      const mine = fresh.filter((e) => e.id.startsWith(`${kind}/`));
      expect(mine).toHaveLength(4);
      expect(mine.every((e) => e.unlocked && e.needs === null)).toBe(true);
    }
  });

  it("every look draws every pose as elements with one body, and each portrait is its own", () => {
    const urls = new Set<string>();
    for (const kind of FREE_KINDS) {
      for (const colour of COMPANIONS[kind]) {
        for (const pose of ["idle", "hop", "cheer", "sleep", "react"] as const) {
          const nodes = parseArt(DRAWINGS[kind].markup(colour, "t", { pose }));
          expect(nodes.filter((n) => n[1].class === "cmp-body")).toHaveLength(1);
          // the cheer's confetti stands outside the body, so the figure jumps through it
          expect(nodes.some((n) => n[1].class === "cmp-confetti")).toBe(pose === "cheer");
        }
        urls.add(DRAWINGS[kind].portraitUrl(colour, true));
        expect(DRAWINGS[kind].colourName(colour).zh).not.toBe("");
      }
    }
    expect(urls.size).toBe(FREE_KINDS.reduce((n, k) => n + COMPANIONS[k].length, 0));
  });

  it("the Tractor carries its rider, in its portrait too", () => {
    const tractor = DRAWINGS.tractor.markup("red", "t", { pose: "idle" });
    expect(tractor).toContain('class="cmp-rider"');
    expect(decodeURIComponent(DRAWINGS.tractor.portraitUrl("red", false))).toContain("cmp-rider");
  });

  it("at the table a team wears its colour and stands on its ground shadow, with no team pad", () => {
    for (const kind of FREE_KINDS) {
      const us = DRAWINGS[kind].markup(COMPANIONS[kind][0], "t", { team: "us" });
      const them = DRAWINGS[kind].markup(COMPANIONS[kind][0], "t", { team: "them" });
      for (const svg of [us, them]) {
        expect(svg).not.toContain("cmp-pad");
        expect(svg).toContain('class="cmp-shadow"');
      }
      expect(us).toContain("#5b9dff");
      expect(them).toContain("#ff9d4d");
      expect(DRAWINGS[kind].markup(COMPANIONS[kind][0], "t", {})).not.toContain("cmp-pad");
    }
  });

  it("the drawn characters take the shared hop and cheer; the Tractor keeps its own", async () => {
    await draw(<><Companion kind="sparrow" colour="tree" size={80} state="cheer" /><Companion colour="red" size={80} state="cheer" /></>);
    const [sparrow, tractor] = [...host.querySelectorAll("svg.cmp")];
    expect([...sparrow.classList]).toEqual(["cmp", "cmp-char", "cmp-sparrow", "cmp-cheer"]);
    expect([...tractor.classList]).toEqual(["cmp", "cmp-tractor", "cmp-cheer"]);
  });

  it("a still pose drops its animation and ends on its own", async () => {
    vi.useFakeTimers();
    try {
      const end = vi.fn();
      await act(async () => { root.render(<Companion kind="bun" colour="taro" size={80} state="react" still onPoseEnd={end} />); });
      expect(host.querySelector("svg.cmp")!.classList.contains("cmp-react")).toBe(false);
      act(() => { vi.advanceTimersByTime(1000); });
      expect(end).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("level growth", () => {
  it("grows a step a level that shows (3 px on a phone, 4 on a tablet) from 2 to the seat cap at 6", () => {
    expect(levelIndex("2")).toBe(0);
    expect(levelIndex("A")).toBe(12);
    expect(levelIndex(undefined)).toBe(0);
    const { phone, tablet } = SEAT_SIZE;
    const at = (s: { base: number; max: number }, ranks: string[]) => ranks.map((r) => companionSize(s.base, levelIndex(r), s.max));
    expect(at(phone, ["2", "3", "4", "5", "6", "9", "A"])).toEqual([44, 47, 50, 53, 56, 56, 56]);
    expect(at(tablet, ["2", "3", "4", "5", "6", "9", "A"])).toEqual([60, 64, 68, 72, 76, 76, 76]);
    expect(companionSize(80, 3, Number.POSITIVE_INFINITY)).toBe(80);
  });

  it("a level gained pops the figure from its old size; a level lost does not", async () => {
    await draw(<Companion kind="chick" colour="yellow" size={44} max={56} level={0} team="us" />);
    const svg = () => host.querySelector("svg.cmp") as SVGSVGElement;
    expect(svg().getAttribute("width")).toBe("44");
    expect(svg().classList.contains("cmp-grow")).toBe(false);
    await draw(<Companion kind="chick" colour="yellow" size={44} max={56} level={2} team="us" />);
    expect(svg().getAttribute("width")).toBe("50");
    expect(svg().classList.contains("cmp-grow")).toBe(true);
    expect(svg().style.getPropertyValue("--cmp-from")).toBe((44 / 50).toFixed(3));
    const name = "AnimationEvent" in window ? "animationend" : "webkitAnimationEnd";
    act(() => {
      const ev = new Event(name, { bubbles: true }) as Event & { animationName: string };
      Object.defineProperty(ev, "animationName", { value: "cmp-grow" });
      svg().dispatchEvent(ev);
    });
    expect(svg().classList.contains("cmp-grow")).toBe(false);
    await draw(<Companion kind="chick" colour="yellow" size={44} max={56} level={0} team="us" />);
    expect(svg().classList.contains("cmp-grow")).toBe(false);
  });
});

describe("the Collection's grid and the character page", () => {
  const user: AuthUser = {
    name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry",
    rounds_played: 3, ranked_wins: 0, look: "bun/custard", companions: "individual", features: { collection: true },
  };
  const puts: unknown[] = [];
  beforeEach(() => {
    puts.length = 0;
    globalThis.fetch = vi.fn(async (url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body ?? "{}"));
      if (url === "/api/me/look") puts.push(body);
      return { status: 200, json: async () => ({ ...user, ...body }) } as Response;
    }) as unknown as typeof fetch;
  });
  const use = () => host.querySelector(".coll-use") as HTMLButtonElement | null;
  const swatch = (label: string) => [...host.querySelectorAll<HTMLButtonElement>(".coll-swatches .coll-swatch")]
    .find((s) => s.getAttribute("aria-label")!.startsWith(label))!;
  const tile = (name: string) => [...host.querySelectorAll<HTMLButtonElement>(".coll-tile")]
    .find((b) => b.querySelector(".coll-tile-name")!.textContent === name)!;
  const openTile = async (name: string) => {
    await act(async () => { tile(name).click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  };
  const back = async () => { await act(async () => { host.querySelector<HTMLButtonElement>(".coll-back")!.click(); }); };
  const signedIn = () => { authState.current = { status: "in", clientId: "cid", user }; };
  const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

  it("Yours lists the four companions and ticks the one in use; a tile opens its page", async () => {
    signedIn();
    await draw(<CollectionPage />);
    const tiles = [...host.querySelectorAll<HTMLButtonElement>(".coll-yours .coll-tile")];
    expect(tiles.map((b) => b.querySelector(".coll-tile-name")!.textContent)).toEqual(["Tractor", "Bun", "Chick", "Sparrow"]);
    expect(tiles.filter((b) => b.querySelector(".coll-tick")).map((b) => b.querySelector(".coll-tile-name")!.textContent)).toEqual(["Bun"]);
    // the one in use stands small at the top
    expect(host.querySelector(".coll-worn svg.cmp-bun")).not.toBeNull();
    await openTile("Chick");
    expect(puts).toEqual([]);
    expect(host.querySelector(".large-title")?.textContent).toBe("Chick");
    expect(host.querySelector(".char-stage svg.cmp-chick")).not.toBeNull();
    expect(host.querySelector(".coll-status")?.textContent).toBe("Chick · Chick yellow");
    expect(use()?.textContent).toBe("Use");
    await act(async () => { use()!.click(); });
    await settle();
    expect(puts).toEqual([{ look: "chick/yellow" }]);
  });

  it("a colour tap only shows it; Use applies it, In use is inert, and the tick stays on what is in use", async () => {
    signedIn();
    await draw(<CollectionPage />);
    await openTile("Bun");
    expect(use()?.textContent).toBe("In use");
    expect(use()?.disabled).toBe(true);
    await act(async () => { swatch("Taro").click(); });
    await settle();
    expect(puts).toEqual([]);
    expect(swatch("Taro").classList.contains("on")).toBe(true);
    expect(swatch("Custard").querySelector(".coll-tick")).not.toBeNull();
    expect(swatch("Taro").querySelector(".coll-tick")).toBeNull();
    expect(host.querySelector(".coll-status")?.textContent).toBe("Bun · Taro");
    expect(use()?.textContent).toBe("Use");
    await act(async () => { use()!.click(); });
    await settle();
    expect(puts).toEqual([{ look: "bun/taro" }]);
  });

  it("a locked colour's button says what unlocks it and does nothing", async () => {
    signedIn();
    await draw(<CollectionPage />);
    await openTile("Tractor");
    await act(async () => { swatch("Ink black").click(); });
    expect(use()?.textContent).toBe("Win 1,000 ranked rounds to unlock · 0 of 1,000");
    expect(use()?.disabled).toBe(true);
    await act(async () => { swatch("Imperial yellow").click(); });
    expect(use()?.textContent).toBe("Win 10 ranked rounds to unlock · 0 of 10");
    authState.current = { status: "in", clientId: "cid", user: { ...user, ranked_wins: 3 } };
    await draw(<CollectionPage />);         // still on the Tractor's page
    await act(async () => { swatch("Lantern orange").click(); });
    expect(use()?.textContent).toBe("Win 25 ranked rounds to unlock · 3 of 25");
    await settle();
    expect(puts).toEqual([]);
  });

  it("has no leaderboard row", async () => {
    signedIn();
    await draw(<CollectionPage />);
    expect(host.querySelector(".coll-row, .lb-row")).toBeNull();
  });

  it("a guest's button reads Sign in to use, and no count is shown", async () => {
    await draw(<CollectionPage />);
    await openTile("Bun");
    expect(use()?.textContent).toBe("Sign in to use");
    await back();
    await openTile("Tractor");
    await act(async () => { swatch("Lantern orange").click(); });
    expect(use()?.textContent).toBe("Sign in to use");
    expect(host.textContent).not.toMatch(/ of \d|ranked rounds/);
    expect(swatch("Lantern orange").getAttribute("aria-label")).toBe("Lantern orange");
  });

  it("has no state chips, only Try on your table, which stands it beside a partner on your team's pads", async () => {
    signedIn();
    await draw(<CollectionPage />);
    await openTile("Bun");
    expect([...host.querySelectorAll(".char-chip")].map((b) => b.textContent)).toEqual(["Try on your table"]);
    await act(async () => { host.querySelector<HTMLButtonElement>(".char-chip")!.click(); });
    const figs = [...host.querySelectorAll(".char-stage svg.cmp")];
    expect(figs.map((f) => [...f.classList].filter((c) => /^cmp-(bun|tractor|us)$/.test(c)))).toEqual([
      ["cmp-bun", "cmp-us"], ["cmp-tractor", "cmp-us"]]);
  });

  it("the stage plays its moves by itself", async () => {
    vi.useFakeTimers();
    try {
      signedIn();
      await act(async () => { root.render(<CollectionPage />); });
      await act(async () => { tile("Bun").click(); });
      const pose = () => [...host.querySelector(".char-stage svg.cmp")!.classList].find((c) => /^cmp-(idle|hop|cheer|sleep|react)$/.test(c));
      expect(pose()).toBe("cmp-idle");
      act(() => { vi.advanceTimersByTime(3100); });       // idle rests 3 s, then the hop
      expect(pose()).toBe("cmp-hop");
    } finally {
      vi.useRealTimers();
    }
  });

  const looksWith = (unlocked: string[]): LookEntry[] => lookCatalogue({ rounds: 0, ranked_wins: 0, ranked_games: 0 }, "bun/custard")
    .map((e) => (unlocked.includes(e.id) ? { ...e, unlocked: true } : e.id === "chick/ink" ? { ...e, unlocked: false } : e));
  const as = (over: Partial<AuthUser> & { unlocked?: string[] } = {}) => {
    const { unlocked = [], ...rest } = over;
    authState.current = { status: "in", clientId: "cid", user: { ...user, looks: looksWith(unlocked), ...rest } };
  };
  const withLooks = (unlocked: string[]) => as({ unlocked });
  const newOn = () => [...host.querySelectorAll(".coll-swatch")].filter((s) => s.querySelector(".coll-new"))
    .map((s) => s.getAttribute("aria-label"));
  const tilesNew = () => [...host.querySelectorAll(".coll-tile")].filter((b) => b.querySelector(".coll-new"))
    .map((b) => b.querySelector(".coll-tile-name")!.textContent);
  const statusLine = () => host.querySelector(".char-page .coll-status")?.textContent;
  // an account's first reading: what it has then is never new
  const firstReading = async (over: Parameters<typeof as>[0] = {}) => {
    as(over);
    await draw(<CollectionPage />);
    await draw(<></>);
    window.history.replaceState(null, "", "/");   // leaving the tab leaves its address
  };

  it("a colour newly unlocked marks its tile, and on its page its swatch, New until that page has been opened", async () => {
    await firstReading();
    expect(tilesNew()).toEqual([]);
    withLooks(["tractor/yellow"]);
    await draw(<CollectionPage />);
    expect(tilesNew()).toEqual(["Tractor"]);
    await openTile("Tractor");
    expect(statusLine()).toBe("Tractor · Imperial yellow");
    expect(swatch("Imperial yellow").classList.contains("on")).toBe(true);
    expect(swatch("Imperial yellow").querySelector(".coll-new")?.textContent).toBe("New");
    expect(newOn()).toEqual(["Imperial yellow New"]);
    await back();
    expect(tilesNew()).toEqual([]);
    // seen: a reload shows it as any other colour
    await draw(<></>);
    window.history.replaceState(null, "", "/");   // leaving the tab leaves its address
    await draw(<CollectionPage />);
    expect(tilesNew()).toEqual([]);
    await openTile("Tractor");
    expect(newOn()).toEqual([]);
    expect(statusLine()).toBe("Tractor · Icon red");
  });

  it("New survives a reload until its page is opened, and a tap on the swatch clears it", async () => {
    await firstReading();
    withLooks(["tractor/yellow", "chick/ink"]);
    // the grid alone sees nothing, across a reload
    await draw(<CollectionPage />);
    await draw(<></>);
    window.history.replaceState(null, "", "/");   // leaving the tab leaves its address
    expect(hasNewLook("j@x", looksWith(["tractor/yellow", "chick/ink"]))).toBe(true);
    await draw(<CollectionPage />);
    expect(tilesNew()).toEqual(["Tractor", "Chick"]);
    await openTile("Tractor");
    expect(newOn()).toEqual(["Imperial yellow New"]);
    await act(async () => { swatch("Imperial yellow").click(); });
    expect(newOn()).toEqual([]);
    await back();
    expect(tilesNew()).toEqual(["Chick"]);
    await openTile("Chick");
    expect(newOn()).toEqual(["Silkie black New"]);
  });

  it("the tab dot stays while a new look is unseen and clears once each one's page is opened or it is put in use", async () => {
    const all = looksWith(["tractor/yellow", "chick/ink"]);
    await firstReading();
    expect(hasNewLook("j@x", looksWith([]))).toBe(false);
    expect(hasNewLook("j@x", all)).toBe(true);
    withLooks(["tractor/yellow", "chick/ink"]);
    await draw(<CollectionPage />);
    expect(hasNewLook("j@x", all)).toBe(true);
    // the Tractor's page sees the Tractor's; the Chick's still holds the dot
    await openTile("Tractor");
    expect(hasNewLook("j@x", all)).toBe(true);
    await back();
    await openTile("Chick");
    expect(hasNewLook("j@x", all)).toBe(false);
    // another account on this device starts with nothing new
    expect(hasNewLook("k@x", all)).toBe(false);
  });

  it("putting a new look in use records it as seen", async () => {
    await firstReading();
    withLooks(["tractor/yellow"]);
    await draw(<CollectionPage />);
    // a write as its page opens is undone here, so only Use records it
    window.localStorage.setItem("shengji.looksSeen", JSON.stringify({ "j@x": looksWith([]).filter((e) => e.unlocked).map((e) => e.id) }));
    expect(hasNewLook("j@x", looksWith(["tractor/yellow"]))).toBe(true);
    await openTile("Tractor");
    window.localStorage.setItem("shengji.looksSeen", JSON.stringify({ "j@x": looksWith([]).filter((e) => e.unlocked).map((e) => e.id) }));
    await act(async () => { use()!.click(); });
    await settle();
    expect(puts).toEqual([{ look: "tractor/yellow" }]);
    expect(hasNewLook("j@x", looksWith(["tractor/yellow"]))).toBe(false);
  });

  it("a new look seen by one account is not recorded for the next one signed in while the Collection stays open", async () => {
    await firstReading({ email: "b@x" });
    await firstReading();
    as({ unlocked: ["tractor/yellow"] });
    await draw(<CollectionPage />);
    await openTile("Tractor");
    expect(newOn()).toEqual(["Imperial yellow New"]);
    // B signs in on the same open page, with yellow still locked: B's own colour
    as({ email: "b@x" });
    await draw(<CollectionPage />);
    expect(statusLine()).toBe("Tractor · Icon red");
    expect(newOn()).toEqual([]);
    await back();
    expect(tilesNew()).toEqual([]);
    expect(JSON.parse(window.localStorage.getItem("shengji.looksSeen")!)["b@x"]).not.toContain("tractor/yellow");
    // when B earns it, it is new for B
    expect(hasNewLook("b@x", looksWith(["tractor/yellow"]))).toBe(true);
    as({ email: "b@x", unlocked: ["tractor/yellow"] });
    await draw(<CollectionPage />);
    expect(tilesNew()).toEqual(["Tractor"]);
    await openTile("Tractor");
    expect(newOn()).toEqual(["Imperial yellow New"]);
    expect(swatch("Imperial yellow").classList.contains("on")).toBe(true);
  });

  it("a viewer signed in on the open page starts from their own look, though it is the same as the last viewer's", async () => {
    await firstReading({ email: "b@x" });
    await firstReading();
    // A, wearing the Bun's Custard, previews the new Imperial yellow
    as({ unlocked: ["tractor/yellow"] });
    await draw(<CollectionPage />);
    await openTile("Tractor");
    expect(swatch("Imperial yellow").classList.contains("on")).toBe(true);
    // B wears the same Custard, with yellow locked: the page starts from B's own
    as({ email: "b@x" });
    await draw(<CollectionPage />);
    expect(statusLine()).toBe("Tractor · Icon red");
    expect(swatch("Imperial yellow").classList.contains("on")).toBe(false);
    await back();
    expect(host.querySelector(".coll-worn svg.cmp-bun")).not.toBeNull();
    await openTile("Bun");
    expect(statusLine()).toBe("Bun · Custard");
    expect(use()?.textContent).toBe("In use");
  });

  it("an unlock a refresh brings marks its tile, and on its open page moves to it unless a colour was tapped there", async () => {
    await firstReading();
    // on the grid: the refresh's new colour marks its tile
    withLooks([]);
    await draw(<CollectionPage />);
    withLooks(["tractor/yellow"]);
    await draw(<CollectionPage />);
    expect(tilesNew()).toEqual(["Tractor"]);
    await draw(<></>);
    window.history.replaceState(null, "", "/");   // leaving the tab leaves its address
    // on the Tractor's page, nothing tapped: it moves to the new colour
    await firstReading({ email: "c@x" });
    as({ email: "c@x" });
    await draw(<CollectionPage />);
    await openTile("Tractor");
    expect(statusLine()).toBe("Tractor · Icon red");
    as({ email: "c@x", unlocked: ["tractor/yellow"] });
    await draw(<CollectionPage />);
    expect(statusLine()).toBe("Tractor · Imperial yellow");
    expect(newOn()).toEqual(["Imperial yellow New"]);
    await draw(<></>);
    window.history.replaceState(null, "", "/");   // leaving the tab leaves its address
    // a colour tapped first stands
    await firstReading({ email: "d@x" });
    as({ email: "d@x" });
    await draw(<CollectionPage />);
    await openTile("Tractor");
    await act(async () => { swatch("Paddy green").click(); });
    as({ email: "d@x", unlocked: ["tractor/yellow"] });
    await draw(<CollectionPage />);
    expect(statusLine()).toBe("Tractor · Paddy green");
    expect(newOn()).toEqual(["Imperial yellow New"]);
  });

  it("a page opened while the refresh is out keeps its colour when the refresh brings a new look and another look in use", async () => {
    await firstReading();
    withLooks([]);
    await draw(<CollectionPage />);
    await openTile("Chick");
    // the refresh: yellow newly unlocked, and the Tractor put in use elsewhere
    as({ look: "tractor/red", unlocked: ["tractor/yellow"] });
    await draw(<CollectionPage />);
    expect(statusLine()).toBe("Chick · Chick yellow");
    expect(hasNewLook("j@x", looksWith(["tractor/yellow"]))).toBe(true);
  });

  it("a colour tapped holds through a refresh that changes the look in use; Use and a Use put back are shown", async () => {
    await firstReading({ look: "chick/yellow" });
    as({ look: "chick/yellow" });
    await draw(<CollectionPage />);
    await openTile("Chick");
    expect(statusLine()).toBe("Chick · Chick yellow");
    await act(async () => { swatch("Cocoa").click(); });
    // another session puts the Chick's Cream in use: the tapped Cocoa stands
    as({ look: "chick/cream" });
    await draw(<CollectionPage />);
    expect(statusLine()).toBe("Chick · Cocoa");
    // Use: the look in use follows, and one put back after a failure is shown again
    await act(async () => { use()!.click(); });
    await settle();
    expect(puts).toEqual([{ look: "chick/cocoa" }]);
    as({ look: "chick/cocoa" });
    await draw(<CollectionPage />);
    as({ look: "chick/cream" });
    await draw(<CollectionPage />);
    expect(statusLine()).toBe("Chick · Cream");
    expect(use()?.textContent).toBe("In use");
  });

  it("one switch, Show at the table, on by default; Off is stored as off and an older Team reads as on", async () => {
    await draw(<CollectionPage />);
    const sw = () => host.querySelector<HTMLButtonElement>(".coll-at-table")!;
    expect(sw().textContent).toBe("Show at the table");
    expect(sw().getAttribute("aria-checked")).toBe("true");
    await act(async () => { sw().click(); });
    expect(window.localStorage.getItem("shengji.companions")).toBe("off");
    expect(sw().getAttribute("aria-checked")).toBe("false");
    window.localStorage.setItem("shengji.companions", "team");
    await draw(<CollectionPage />);
    await draw(<></>);
    window.history.replaceState(null, "", "/");   // leaving the tab leaves its address
    await draw(<CollectionPage />);
    expect(sw().getAttribute("aria-checked")).toBe("true");
  });
});

describe("the table", () => {
  const m = TABLES["phone-land-w2"];
  const player = (seat: number, over: Partial<StatePlayer> = {}): StatePlayer => ({
    seat, name: `P${seat}`, is_bot: false, look: ["bun/plain", "sparrow/tree", "chick/yellow", "tractor/red"][seat],
    connected: true, team: (seat % 2) as 0 | 1, cards_left: 25, is_banker: false, takeover_in: null,
    controller: "human", reserved_for: null, reserved_secs: null, ...over,
  });
  const state = (over: Partial<GameState> = {}): GameState => ({
    you: 0, phase: "play", levels: ["2", "A"], players: [player(0), player(1), player(2), player(3)],
    trick: { leader: 1, plays: [] }, last_trick: null, round_result: null, ...over,
  } as unknown as GameState);
  // a felt measured as the phone's real table, with the rects the zones read
  let rects: Record<string, Rect>;
  let spy: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    authState.current = { status: "out", clientId: "cid", user: null, collection: true } as AuthState;
    rects = { felt: { x: 0, y: 0, ...m.felt }, "pos-left": m.plates.left, "pos-top": m.plates.top, "pos-right": m.plates.right,
              "you-row": m.row!, hand: m.hand, "hand-slot": m.firstCard, "trick-play": { x: 0, y: 0, w: 0, h: 0 } };
    spy = vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      const cls = [...this.classList];
      const k = Object.keys(rects).find((c) => cls.includes(c));
      const r = k ? rects[k] : { x: 0, y: 0, w: 0, h: 0 };
      return { left: r.x, top: r.y, width: r.w, height: r.h, right: r.x + r.w, bottom: r.y + r.h, x: r.x, y: r.y, toJSON: () => ({}) } as DOMRect;
    });
  });
  afterEach(() => { spy.mockRestore(); });
  const table = (s: GameState) => (
    <div className="felt">
      <div className="opponent pos-left" /><div className="opponent pos-top" /><div className="opponent pos-right" />
      <div className="trick-area"><div className="trick-play" /></div>
      <div className="you-row" /><div className="hand"><div className="hand-slot" /></div>
      <TableCompanions state={s} />
    </div>
  );
  const spotOf = (seat: number) => {
    const w = host.querySelector<HTMLElement>(`.tc-seat[data-seat="${seat}"] .tc-walk`)!;
    const [x, y] = /translate\(([-\d.]+)px, ([-\d.]+)px\)/.exec(w.style.transform)!.slice(1).map(Number);
    return { x, y };
  };
  const layout = (): Layout => ({ felt: m.felt, plates: m.plates, tagline: null, row: m.row, hand: m.firstCard,
    obstacles: [rects["trick-play"], { ...m.hand, y: Math.min(m.hand.y, m.firstCard.y - HAND_LIFT), h: m.hand.y + m.hand.h - Math.min(m.hand.y, m.firstCard.y - HAND_LIFT) },
                ...Object.values(m.plates)].filter((r) => r.w > 0) });
  // each seat's zone as the table works it out: yours first, every seat at its team's level
  const homeOf = (pos: SeatPos) => zonesFor([{ pos: "bottom", size: 44, tag: true }, { pos: "left", size: 56, tag: false },
    { pos: "top", size: 44, tag: false }, { pos: "right", size: 56, tag: false }], layout())[pos].home!;

  it("draws nothing unless the Collection is shown and Show at the table is on", async () => {
    authState.current = { status: "out", clientId: "cid", user: null };
    await draw(table(state()));
    expect(host.querySelector(".table-companions")).toBeNull();
    authState.current = { status: "out", clientId: "cid", user: null, collection: true } as AuthState;
    window.localStorage.setItem("shengji.companions", "off");
    await draw(table(state()));
    expect(host.querySelector(".table-companions")).toBeNull();
    window.localStorage.setItem("shengji.companions", "team");
    await draw(table(state({ players: [player(0), player(1), player(2), player(3, { is_bot: true, look: null })] } as Partial<GameState>)));
    // an older Team is on, by each player; a bot has none
    expect([...host.querySelectorAll(".tc-seat")].map((s) => s.getAttribute("data-seat"))).toEqual(["0", "1", "2"]);
  });

  it("a table only being watched draws none", async () => {
    await draw(table(state({ joining_you: true } as Partial<GameState>)));
    expect(host.querySelector(".table-companions")).toBeNull();
  });

  it("a team hops for a trick it takes and cheers for one worth 10 or more; an absent person's companion sleeps", async () => {
    await draw(table(state()));
    const box = (seat: number) => host.querySelector(`.tc-seat[data-seat="${seat}"] .tc-move`)!;
    const fig = (seat: number) => host.querySelector(`.tc-seat[data-seat="${seat}"] svg`)!;
    const players = [player(0), player(1, { connected: false }), player(2), player(3)];
    const small = { leader: 0, winner: 2, points: 5, plays: [{ seat: 0, cards: ["HA"] }] };
    await draw(table(state({ last_trick: small, players } as Partial<GameState>)));
    expect([box(0), box(2)].map((b) => b.getAttribute("data-move"))).toEqual(["hop", "hop"]);
    expect([fig(0), fig(2)].every((f) => f.classList.contains("cmp-rest"))).toBe(true);
    expect(fig(1).classList.contains("cmp-sleep")).toBe(true);
    const big = { leader: 2, winner: 0, points: 10, plays: [{ seat: 2, cards: ["HK"] }] };
    await draw(table(state({ last_trick: big, players } as Partial<GameState>)));
    expect([box(0), box(2)].map((b) => b.getAttribute("data-move"))).toEqual(["cheer", "cheer"]);
    expect([fig(0), fig(2)].every((f) => f.querySelector(".cmp-confetti") !== null)).toBe(true);
  });

  describe("a level gained", () => {
    // every Web Animation started, with the move its box was showing; each
    // ends after its own duration on the fake clock
    let pops: { seat: string | null; move: string | null; frames: Keyframe[] }[];
    let had: unknown;
    const proto = Element.prototype as unknown as { animate?: unknown };
    beforeEach(() => {
      vi.useFakeTimers();
      pops = [];
      had = proto.animate;
      proto.animate = function (this: Element, frames: Keyframe[], opts: KeyframeAnimationOptions) {
        pops.push({ seat: this.closest(".tc-seat")?.getAttribute("data-seat") ?? null, move: this.getAttribute("data-move"), frames });
        let timer = 0;
        const finished = new Promise<void>((r) => { timer = window.setTimeout(r, Number(opts?.duration ?? 0)); });
        return { finished, cancel: () => window.clearTimeout(timer) };
      };
    });
    afterEach(() => { proto.animate = had; vi.useRealTimers(); });
    const render = async (s: GameState) => { await act(async () => { root.render(table(s)); }); };
    const ups = () => pops.filter((p) => p.move === "levelup").map((p) => p.seat).sort();
    const width = (seat: number) => host.querySelector(`.tc-seat[data-seat="${seat}"] svg`)!.getAttribute("width");
    const badges = () => [...host.querySelectorAll(".tc-level")].map((b) => [b.closest(".tc-seat")!.getAttribute("data-seat"), b.textContent]);
    const result = { winner_team: 0, level_change: 2, new_levels: ["4", "A"] };
    const roundEnd = state({ phase: "round_end", levels: ["4", "A"], round_result: result } as unknown as Partial<GameState>);
    const nextRound = state({ phase: "deal", levels: ["4", "A"] } as unknown as Partial<GameState>);

    it("does not move while the round-end sheet is open", async () => {
      await render(state());
      await render(roundEnd);
      act(() => { vi.advanceTimersByTime(3000); });
      expect(ups()).toEqual([]);
      expect(pops.filter((p) => p.seat !== null && p.move !== "idle")).toEqual([]);
      expect(badges()).toEqual([]);
      // the figures still stand at the level the round was played at
      expect([width(0), width(2)]).toEqual(["44", "44"]);
    });

    it("pops each of the team's companions once when the sheet closes, to its new size, with the new level", async () => {
      await render(state());
      await render(roundEnd);
      await render(nextRound);
      expect(ups()).toEqual(["0", "2"]);
      expect([width(0), width(2)]).toEqual(["50", "50"]);
      // the pop starts at the old size over the new and overshoots it
      const frames = pops.find((p) => p.move === "levelup")!.frames;
      expect(frames[0].transform).toContain(`scale(${(44 / 50).toFixed(3)})`);
      expect(frames.some((f) => /scale\(1\.2/.test(String(f.transform)))).toBe(true);
      expect(badges()).toEqual([["0", "4"], ["2", "4"]]);
      // the wrapper plays the pop: the drawing itself never grows on top of it
      expect([0, 2].map((seat) => host.querySelector(`.tc-seat[data-seat="${seat}"] svg`)!.classList.contains("cmp-grow"))).toEqual([false, false]);
      // later states of the same level move nothing again
      await render(state({ phase: "play", levels: ["4", "A"] } as unknown as Partial<GameState>));
      act(() => { vi.advanceTimersByTime(LEVEL_UP_MS + 10); });
      await render(state({ phase: "play", levels: ["4", "A"], trick: { leader: 0, plays: [] } } as unknown as Partial<GameState>));
      expect(ups()).toEqual(["0", "2"]);
      expect(badges()).toEqual([]);
    });

    it("moves no companion whose team's level did not change", async () => {
      await render(state());
      const held = { winner_team: 1, level_change: 0, new_levels: ["2", "A"] };
      await render(state({ phase: "round_end", round_result: held } as unknown as Partial<GameState>));
      await render(state({ phase: "deal" } as unknown as Partial<GameState>));
      expect(ups()).toEqual([]);
      // the other team (at A throughout) does not move when this one climbs
      await render(roundEnd);
      await render(nextRound);
      expect(ups()).toEqual(["0", "2"]);
      // a new game's levels starting over shrink with no move
      act(() => { vi.advanceTimersByTime(LEVEL_UP_MS + 10); });
      await render(state({ phase: "deal", levels: ["2", "2"] } as unknown as Partial<GameState>));
      expect(ups()).toEqual(["0", "2"]);
      expect(width(1)).toBe("44");
    });

    it("waits for a hidden page to be shown again", async () => {
      let hidden = false;
      const vis = vi.spyOn(document, "visibilityState", "get").mockImplementation(() => (hidden ? "hidden" : "visible"));
      try {
        await render(state());
        await render(roundEnd);
        hidden = true;
        act(() => { document.dispatchEvent(new Event("visibilitychange")); });
        await render(nextRound);
        expect(ups()).toEqual([]);
        hidden = false;
        await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
        expect(ups()).toEqual(["0", "2"]);
      } finally {
        vis.mockRestore();
      }
    });
  });

  it("is the default: each person's companion stands by their nameplate, clear of the table, yours tagged You by your hand", async () => {
    await draw(table(state()));
    const seats = [...host.querySelectorAll(".tc-seat")];
    expect(seats.map((s) => [s.getAttribute("data-seat"), s.getAttribute("data-pos")])).toEqual([
      ["0", "bottom"], ["1", "left"], ["2", "top"], ["3", "right"]]);
    expect([...host.querySelectorAll(".tc-you")].map((t) => t.closest(".tc-seat")!.getAttribute("data-seat"))).toEqual(["0"]);
    for (const s of [0, 1, 2, 3]) {
      const svg = host.querySelector(`.tc-seat[data-seat="${s}"] svg`)!;
      expect(Number(svg.getAttribute("width"))).toBeLessThanOrEqual(56);
      expect(clear(spotOf(s), Number(svg.getAttribute("width")), s === 0, layout())).toBe(true);
    }
    // each stands under or beside its own nameplate
    const near = (s: number, plate: Rect) => Math.hypot(spotOf(s).x - plate.x, spotOf(s).y - plate.y) < 120;
    expect(near(1, m.plates.left) && near(2, m.plates.top) && near(3, m.plates.right)).toBe(true);
    // yours stands over the left end of your hand, not under the left seat
    expect(Math.abs(spotOf(0).x - m.firstCard.x)).toBeLessThan(3 * 44);
    expect(spotOf(0).y + 44).toBeLessThanOrEqual(m.firstCard.y - HAND_LIFT);
  });

  it("grows by level within the seat cap", async () => {
    await draw(table(state()));
    expect(host.querySelector('.tc-seat[data-seat="0"] svg')!.getAttribute("width")).toBe("44");
    expect(host.querySelector('.tc-seat[data-seat="1"] svg')!.getAttribute("width")).toBe("56");
  });

  it("walks now and then within its zone, facing the way it goes, and never while hidden", async () => {
    vi.useFakeTimers();
    // a fixed draw: every walk waits 11.5 s and goes to its zone's middle far spot, which each seat can reach
    const rnd = vi.spyOn(Math, "random").mockReturnValue(0.5);
    let hidden = false;
    const vis = vi.spyOn(document, "visibilityState", "get").mockImplementation(() => (hidden ? "hidden" : "visible"));
    const walks: { el: Element; frames: Keyframe[] }[] = [];
    const proto = Element.prototype as unknown as { animate?: unknown };
    const had = proto.animate;
    proto.animate = function (this: Element, frames: Keyframe[]) {
      walks.push({ el: this, frames });
      return { finished: new Promise(() => {}), cancel: () => {} };
    };
    try {
      await act(async () => { root.render(table(state())); });
      const start = spotOf(1);
      act(() => { vi.advanceTimersByTime(7900); });
      expect(walks.filter((w) => w.el.classList.contains("tc-walk"))).toHaveLength(0);
      act(() => { vi.advanceTimersByTime(7200); });
      const moved = walks.filter((w) => w.el.classList.contains("tc-walk"));
      expect(new Set(moved.map((w) => w.el.closest(".tc-seat")!.getAttribute("data-seat")))).toEqual(new Set(["0", "1", "2", "3"]));
      // each has fidgeted too, on its move box, by 10 s
      expect(new Set(walks.filter((w) => w.el.classList.contains("tc-move")).map((w) => w.el.closest(".tc-seat")!.getAttribute("data-seat"))))
        .toEqual(new Set(["0", "1", "2", "3"]));
      const end = spotOf(1);
      expect(Math.hypot(end.x - start.x, end.y - start.y)).toBeGreaterThan(0);
      expect(clear(end, 56, false, layout())).toBe(true);
      const facing = host.querySelector<HTMLElement>('.tc-seat[data-seat="1"] .tc-face')!.style.transform;
      expect(facing).toBe(end.x < start.x ? "scaleX(-1)" : "scaleX(1)");
      hidden = true;
      act(() => { document.dispatchEvent(new Event("visibilitychange")); });
      const n = walks.length;
      act(() => { vi.advanceTimersByTime(60000); });
      expect(walks.length).toBe(n);
    } finally {
      proto.animate = had;
      vis.mockRestore();
      rnd.mockRestore();
      vi.useRealTimers();
    }
  });

  it("steps off a spot cards land on", async () => {
    await draw(table(state()));
    const was = spotOf(1);
    rects["trick-play"] = { x: was.x - 6, y: was.y - 6, w: 60, h: 60 };
    await draw(table(state({ trick: { leader: 1, plays: [{ seat: 1, cards: ["HA"] }] } } as Partial<GameState>)));
    const now = spotOf(1);
    expect(now).not.toEqual(was);
    expect(clear(now, 56, false, layout())).toBe(true);
  });

  it("a figure whose whole zone cards cover steps out to the nearest clear spot, never off the table, and goes home when they clear", async () => {
    const mm = window.matchMedia;
    window.matchMedia = ((q: string) => ({ matches: q.includes("reduce"), addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
    try {
      await draw(table(state()));
      const home = homeOf("left");
      expect(spotOf(1)).toEqual(home);
      // cards over the whole of seat 1's corner: it has nowhere clear to stand
      rects["trick-play"] = { x: 0, y: 40, w: 340, h: 225 };
      await draw(table(state({ trick: { leader: 1, plays: [{ seat: 1, cards: ["HA"] }] } } as Partial<GameState>)));
      expect(host.querySelector('.tc-seat[data-seat="1"]')).not.toBeNull();
      const out = spotOf(1);
      expect(meets(figureBox(out, 56, false), rects["trick-play"])).toBe(false);
      expect(clear(out, 56, false, { ...layout(), obstacles: [...layout().obstacles, rects["trick-play"]] })).toBe(true);
      rects["trick-play"] = { x: 0, y: 0, w: 0, h: 0 };
      await draw(table(state({ trick: { leader: 2, plays: [] } } as Partial<GameState>)));
      const w = host.querySelector<HTMLElement>('.tc-seat[data-seat="1"] .tc-walk')!;
      expect(w.style.transform).toBe(`translate(${home.x}px, ${home.y}px)`);
    } finally {
      window.matchMedia = mm;
    }
  });

  it("a card landing across a walk in flight stops the walk and its gait, and the figure ends clear", async () => {
    vi.useFakeTimers();
    // one fixed draw: the same wait, the same walk, the same destination every run
    const rnd = vi.spyOn(Math, "random").mockReturnValue(0.5);
    const made: { el: Element; cancel: ReturnType<typeof vi.fn> }[] = [];
    const proto = Element.prototype as unknown as { animate?: unknown };
    const had = proto.animate;
    proto.animate = function (this: Element) {
      const cancel = vi.fn();
      made.push({ el: this, cancel });
      return { finished: new Promise(() => {}), cancel };
    };
    try {
      await act(async () => { root.render(table(state())); });
      const seat1 = () => made.filter((a) => a.el.closest('.tc-seat[data-seat="1"]') && !a.el.classList.contains("tc-move"));
      for (let i = 0; i < 200 && seat1().length === 0; i++) act(() => { vi.advanceTimersByTime(100); });
      const flight = seat1();
      expect(flight.map((a) => a.el.className)).toEqual(["tc-walk", "tc-face"]);
      const to = spotOf(1);
      rects["trick-play"] = { x: to.x - 4, y: to.y - 4, w: 50, h: 50 };
      await act(async () => { root.render(table(state({ trick: { leader: 1, plays: [{ seat: 1, cards: ["HA"] }] } } as Partial<GameState>))); });
      expect(flight.every((a) => a.cancel.mock.calls.length >= 1)).toBe(true);
      expect(clear(spotOf(1), 56, false, layout())).toBe(true);
    } finally {
      rnd.mockRestore();
      proto.animate = had;
      vi.useRealTimers();
    }
  });

  describe("taps and moves", () => {
    // every Web Animation started on a figure: its seat, which box, its frames;
    // each ends after its own duration on the fake clock
    let anims: { seat: string | null; box: string; move: string | null; frames: Keyframe[]; ms: number; cancel: ReturnType<typeof vi.fn> }[];
    let had: unknown;
    let rnd: ReturnType<typeof vi.spyOn>;
    const proto = Element.prototype as unknown as { animate?: unknown };
    beforeEach(() => {
      vi.useFakeTimers();
      rnd = vi.spyOn(Math, "random").mockReturnValue(0.5);
      anims = [];
      had = proto.animate;
      proto.animate = function (this: Element, frames: Keyframe[], opts: KeyframeAnimationOptions) {
        let timer = 0;
        const finished = new Promise<void>((r) => { timer = window.setTimeout(r, Number(opts?.duration ?? 0) * Number(opts?.iterations ?? 1)); });
        const cancel = vi.fn(() => window.clearTimeout(timer));
        anims.push({ seat: this.closest(".tc-seat")?.getAttribute("data-seat") ?? null, box: this.className.toString(),
                     move: this.getAttribute("data-move"), frames, ms: Number(opts?.duration ?? 0), cancel });
        return { finished, cancel };
      };
    });
    afterEach(() => { proto.animate = had; rnd.mockRestore(); vi.useRealTimers(); });
    const render = async (s: GameState) => { await act(async () => { root.render(table(s)); }); };
    const tap = (el: Element, x: number, y: number) => act(() => {
      el.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: x, clientY: y }));
    });
    // the fake clock moves, and the moves it ends settle
    const advance = async (ms: number) => {
      await act(async () => { vi.advanceTimersByTime(ms); for (let i = 0; i < 6; i++) await Promise.resolve(); });
      await act(async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); });
    };
    const walks = (seat: string) => anims.filter((a) => a.seat === seat && a.box.split(" ").includes("tc-walk"));
    // a special drawn larger is its own animation of the move box, apart from the moves
    const grow = (a: { frames: Keyframe[] }) => /^scale\([\d.]+\)$/.test(String(a.frames[1]?.transform));
    const moves = (seat: string) => anims.filter((a) => a.seat === seat && a.box === "tc-move" && !grow(a));
    const grows = (seat: string) => anims.filter((a) => a.seat === seat && a.box === "tc-move" && grow(a));
    const felt = () => host.querySelector(".felt")!;

    it("a tap on empty felt walks your companion to the clear spot nearest the tap, and nothing else moves", async () => {
      await render(state({ players: [player(0), player(1, { is_bot: true, look: null }), player(2, { is_bot: true, look: null }), player(3, { is_bot: true, look: null })] } as Partial<GameState>));
      const target = { x: 420, y: 220 };
      tap(felt(), target.x, target.y);
      expect(walks("0")).toHaveLength(1);
      const end = spotOf(0);
      expect(clear(end, 44, true, layout())).toBe(true);
      // its feet near the tap
      expect(Math.hypot(end.x + 22 - target.x, end.y + 44 - target.y)).toBeLessThan(80);
      // it stays there until its next walk
      act(() => { vi.advanceTimersByTime(5000); });
      expect(spotOf(0)).toEqual(end);
    });

    // every spot yours walks to from the walks numbered `from` on
    const stops = (from: number) => walks("0").slice(from).map((w) => {
      const [x, y] = /translate\(([-\d.]+)px, ([-\d.]+)px\)/.exec(String(w.frames[1].transform))!.slice(1).map(Number);
      return { x, y };
    });
    const near = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y);
    const cycle = (vals: number[]) => { let i = 0; rnd.mockImplementation(() => vals[i++ % vals.length]); };

    it("the spot a tap chose is yours' home from then on: 30 s of idle walks stay round it, never back by your hand", async () => {
      await render(state());
      const home = spotOf(0);
      tap(felt(), 420, 220);
      const end = spotOf(0);
      expect(near(end, home)).toBeGreaterThan(100);
      const taken = walks("0").length;
      cycle([0.05, 0.95, 0.3, 0.7]);
      for (let t = 0; t < 30000; t += 1000) await advance(1000);
      const after = stops(taken);
      // it did walk, each walk a small one round the tapped spot, every spot clear
      expect(after.length).toBeGreaterThanOrEqual(2);
      for (const s of after) {
        expect(near(s, end)).toBeLessThanOrEqual(44);
        expect(clear(s, 44, true, layout())).toBe(true);
      }
      expect(near(spotOf(0), end)).toBeLessThanOrEqual(44);
    });

    it("with only its old area by your hand covered, yours stays drawn on its tapped home and takes a second tap", async () => {
      const bots = state({ players: [player(0), player(1, { is_bot: true, look: null }), player(2, { is_bot: true, look: null }), player(3, { is_bot: true, look: null })] } as Partial<GameState>);
      await render(bots);
      tap(felt(), 420, 220);
      await advance(2000);
      const end = spotOf(0);
      expect(end).toEqual({ x: 397, y: 175 });
      rects["trick-play"] = { x: 0, y: 40, w: 340, h: 225 };
      await render({ ...bots, trick: { leader: 1, plays: [{ seat: 1, cards: ["HA"] }] } } as GameState);
      await advance(2000);
      // the hand zone has nowhere clear, the tapped home is still clear: it stays drawn there
      expect(clear(end, 44, true, layout())).toBe(true);
      expect(host.querySelector('.tc-seat[data-seat="0"]')).not.toBeNull();
      expect(spotOf(0)).toEqual(end);
      const before = walks("0").length;
      tap(felt(), 470, 230);
      expect(walks("0").length).toBe(before + 1);
      const second = spotOf(0);
      expect(second).not.toEqual(end);
      expect(clear(second, 44, true, layout())).toBe(true);
    });

    it("with nothing clear near the tapped home, yours drops it and stands in its zone by your hand at the zone's size", async () => {
      const bots = state({ players: [player(0), player(1, { is_bot: true, look: null }), player(2, { is_bot: true, look: null }), player(3, { is_bot: true, look: null })] } as Partial<GameState>);
      await render(bots);
      tap(felt(), 420, 220);
      await advance(2000);
      expect(spotOf(0)).toEqual({ x: 397, y: 175 });
      rects["trick-play"] = { x: 0, y: 0, w: 844, h: 200 };
      await render({ ...bots, trick: { leader: 1, plays: [{ seat: 1, cards: ["HA"] }] } } as GameState);
      await advance(2000);
      const zone = zonesFor([{ pos: "bottom", size: 44, tag: true }], layout()).bottom;
      expect(zone.home).not.toBeNull();
      expect(zone.size).toBeLessThan(44);
      // drawn at the zone's size, the whole figure and its You tag clear at that size
      const w = Number(host.querySelector('.tc-seat[data-seat="0"] svg')!.getAttribute("width"));
      expect(w).toBe(zone.size);
      const at = spotOf(0);
      expect(clear(at, w, true, layout())).toBe(true);
      expect(zone.spots).toContainEqual(at);
      // and no tapped home is left: later walks stay in the zone
      for (let t = 0; t < 30000; t += 1000) await advance(1000);
      expect(zone.spots).toContainEqual(spotOf(0));
    });

    // an element added to the felt (or the screen) as the page would, measured where `rects` says
    const add = (cls: string, at: Rect, parent: Element = felt()) => {
      const el = document.createElement("div");
      el.className = cls;
      rects[cls.split(" ").at(-1)!] = at;
      parent.appendChild(el);
      return el;
    };
    // the observer's next frame, and the walk it starts
    const settle = async (ms = 500) => { await act(async () => { await Promise.resolve(); }); await advance(ms); };
    const boxOf = (seat: number, px = 44) => figureBox(spotOf(seat), px, seat === 0);

    it("a control that appears over yours (the clock's ring) is drawn over it, and yours walks clear within half a second", async () => {
      await render(state());
      const was = spotOf(0);
      const bar = add("action-bar", { x: 0, y: 0, w: 0, h: 0 });
      const ring: Rect = { x: was.x - 4, y: was.y - 4, w: 44, h: 44 };
      add("timer-ring", ring, bar);
      await settle(500);
      const hop = walks("0");
      expect(hop).toHaveLength(1);
      expect(hop[0].ms).toBeLessThanOrEqual(500);
      expect(meets(boxOf(0), ring)).toBe(false);
      // out the way up, not down into the hand
      expect(spotOf(0).y).toBeLessThanOrEqual(was.y);
    });

    for (const [phase, row] of [
      ["deal", [["deal-deck", { x: 401, y: 77, w: 48, h: 66 }], ["deal-deck-count", { x: 390, y: 148, w: 72, h: 23 }]]],
      ["declare", [["you-tagline", { x: 317, y: 229, w: 37, h: 30 }], ["timer-ring", { x: 315, y: 190, w: 44, h: 44 }],
                   ["btn", { x: 362, y: 229, w: 66, h: 27 }], ["declare-tag", { x: 436, y: 221, w: 53, h: 43 }]]],
      ["bury", [["btn", { x: 377, y: 222, w: 90, h: 40 }], ["timer-ring", { x: 315, y: 190, w: 44, h: 44 }]]],
      ["play", [["you-tagline", { x: 325, y: 241, w: 37, h: 30 }], ["timer-ring", { x: 315, y: 190, w: 44, h: 44 }],
                ["your-turn-tag", { x: 371, y: 234, w: 109, h: 43 }], ["hand-line", { x: 300, y: 250, w: 240, h: 16 }]]],
      ["round_end", []],
    ] as const) {
      it(`as banker in ${phase} on a phone, yours and its tag clear every control of the row`, async () => {
        await render(state({ phase } as Partial<GameState>));
        const bar = add("action-bar", { x: 0, y: 0, w: 0, h: 0 });
        const placed: Rect[] = [];
        for (const [cls, r] of row) {
          const el = add(cls === "you-tagline" || cls === "hand-line" || cls.startsWith("deal") ? cls : `x ${cls}`, r,
                         cls === "you-tagline" || cls === "hand-line" || cls.startsWith("deal") ? felt() : bar);
          if (!cls.startsWith("deal") && cls !== "you-tagline" && cls !== "hand-line") { el.className = cls; rects[cls] = r; }
          placed.push(r);
        }
        await settle(1500);
        for (const r of placed) expect(meets(boxOf(0), r), JSON.stringify(r)).toBe(false);
      });
    }

    it("a chat bubble shown over a companion has it walk clear", async () => {
      await act(async () => { root.render(<div className="table-screen">{table(state())}<div className="chat-bubbles" /></div>); });
      const was = spotOf(1);
      const bubble: Rect = { x: was.x - 10, y: was.y + 6, w: 80, h: 30 };
      add("chat-bubble", bubble, host.querySelector(".chat-bubbles")!);
      await settle(500);
      expect(walks("1")).toHaveLength(1);
      expect(meets(boxOf(1, 56), bubble)).toBe(false);
    });

    it("a tap while the menu, Chat or Last trick is open (or the tap that closes one) leaves yours where it is", async () => {
      await render(state());
      for (const cls of ["hud-menu", "chat-panel", "last-trick-panel"]) {
        const el = add(cls, { x: 600, y: 60, w: 200, h: 120 }, cls === "last-trick-panel" ? felt() : document.body);
        tap(felt(), 420, 220);
        await advance(600);
        expect(walks("0")).toHaveLength(0);
        // the tap that closes it: open as it begins, gone by its click
        felt().dispatchEvent(new Event("pointerdown", { bubbles: true }));
        el.remove();
        tap(felt(), 420, 220);
        await advance(600);
        expect(walks("0")).toHaveLength(0);
        felt().dispatchEvent(new Event("pointerdown", { bubbles: true }));
      }
      // with none open, a tap walks it
      tap(felt(), 420, 220);
      expect(walks("0")).toHaveLength(1);
    });

    it("an open Last trick over yours has it walk out from under", async () => {
      await render(state());
      const was = spotOf(0);
      const panel: Rect = { x: was.x + 20, y: was.y - 30, w: 200, h: 50 };
      add("last-trick-panel", panel);
      await settle(500);
      expect(walks("0")).toHaveLength(1);
      expect(meets(boxOf(0), panel)).toBe(false);
    });

    it("never stands under a notch or the Dynamic Island: a 59 px left inset keeps every figure right of it", async () => {
      const real = window.getComputedStyle;
      const cs = vi.spyOn(window, "getComputedStyle").mockImplementation((el: Element, p?: string | null) => {
        const out = real(el, p);
        if (!el.classList.contains("tc-safe-probe")) return out;
        return { ...out, paddingLeft: "59px", paddingRight: "0px", paddingTop: "0px", paddingBottom: "21px" } as CSSStyleDeclaration;
      });
      try {
        await render(state());
        for (const seat of [0, 1, 2, 3]) {
          const w = Number(host.querySelector(`.tc-seat[data-seat="${seat}"] svg`)!.getAttribute("width"));
          const b = figureBox(spotOf(seat), w, seat === 0);
          expect(b.x, `seat ${seat}`).toBeGreaterThanOrEqual(59);
          expect(b.y + b.h, `seat ${seat}`).toBeLessThanOrEqual(390 - 21);
        }
        // the partner's stays by its nameplate (the left seat's)
        const left = m.plates.left;
        expect(Math.abs(spotOf(1).y - (left.y + left.h))).toBeLessThan(60);
      } finally {
        cs.mockRestore();
      }
    });

    it("a special is drawn larger for its length where there is room; a tap in its cooldown answers with a small hop", async () => {
      await render(state());
      tap(host.querySelector('.tc-seat[data-seat="0"] .tc-walk')!, 0, 0);
      const g = grows("0");
      expect(g).toHaveLength(1);
      const k = Number(/scale\(([\d.]+)\)/.exec(String(g[0].frames[1].transform))![1]);
      expect(k).toBeGreaterThanOrEqual(1.2);
      expect(k).toBeLessThanOrEqual(1.5);
      expect(g[0].ms).toBe(DRAWINGS.bun.reactMs);
      const s = spotOf(0);
      expect(clear({ x: s.x - ((k - 1) * 44) / 2, y: s.y - (k - 1) * 44 }, 44 * k, true, layout())).toBe(true);
      await advance(1700);
      const before = moves("0").length;
      tap(host.querySelector('.tc-seat[data-seat="0"] .tc-walk')!, 0, 0);
      const nudge = moves("0").slice(before);
      expect(nudge).toHaveLength(1);
      expect(nudge[0].frames).toEqual(MOVES.nudge.frames);
      expect(specialOn("0")).toBe(false);
    });

    it("no move lifts a figure past the room its zone keeps over it", () => {
      for (const [name, mv] of Object.entries(MOVES)) {
        for (const f of mv.frames) {
          const t = String(f.transform);
          const y = Number(/translateY\((-?[\d.]+)%\)/.exec(t)?.[1] ?? 0);
          const sy = Number(/scale\([\d.]+, ([\d.]+)\)/.exec(t)?.[1] ?? 1);
          expect(-y / 100 + (sy - 1), name).toBeLessThanOrEqual(LIFT + 1e-9);
        }
      }
    });

    it("a tapped walk goes round another companion in two legs, never through it", async () => {
      await render(state());
      const from = spotOf(0);
      const zones = zonesFor([{ pos: "bottom", size: 44, tag: true }, { pos: "left", size: 56, tag: false },
        { pos: "top", size: 44, tag: false }, { pos: "right", size: 56, tag: false }], layout());
      const peers = (["left", "top", "right"] as const).flatMap((pos) => zones[pos].spots.map((q) => figureBox(q, zones[pos].size ?? 44, false)));
      const others: Layout = { ...layout(), obstacles: peers };
      // a tap whose straight way crosses the left seat's companion
      let target: { x: number; y: number } | null = null;
      for (let y = 60; y < 200 && !target; y += 10) {
        for (let x = 120; x < 400 && !target; x += 10) {
          const to = { x: x - 22, y: y - 44 };
          if (clear(to, 44, true, { ...layout(), obstacles: [...layout().obstacles, ...peers] }) && !pathClear(from, to, 44, true, others)) target = { x, y };
        }
      }
      expect(target).not.toBeNull();
      tap(felt(), target!.x, target!.y);
      const w = walks("0");
      expect(w).toHaveLength(1);
      expect(w[0].frames).toHaveLength(3);
      const pt = (f: Keyframe) => { const [x, y] = /translate\(([-\d.]+)px, ([-\d.]+)px\)/.exec(String(f.transform))!.slice(1).map(Number); return { x, y }; };
      const [a, via, b] = w[0].frames.map(pt);
      expect(pathClear(a, via, 44, true, others) && pathClear(via, b, 44, true, others)).toBe(true);
      expect(around(a, b, 44, true, others)).toEqual(via);
    });

    it("cards flying in are measured where they land: a companion there steps aside as they set off", async () => {
      await render(state());
      const was = spotOf(1);
      // the trick's box mid-flight is far off; its landing is on the left seat's companion
      const landing: Rect = { x: was.x + 4, y: was.y + 10, w: 30, h: 30 };
      const flying = { x: 400, y: 300 };
      rects["trick-play"] = { ...landing, x: flying.x, y: flying.y };
      (host.querySelector(".trick-play") as HTMLElement).style.transform = `matrix(1, 0, 0, 1, ${flying.x - landing.x}, ${flying.y - landing.y})`;
      await render(state({ trick: { leader: 1, plays: [{ seat: 1, cards: ["HA"] }] } } as Partial<GameState>));
      expect(walks("1")).toHaveLength(1);
      await advance(500);
      expect(meets(boxOf(1, 56), landing)).toBe(false);
    });

    // the four people's figures, each at its drawn size
    const figure = (seat: number) => {
      const w = Number(host.querySelector(`.tc-seat[data-seat="${seat}"] svg`)!.getAttribute("width"));
      return figureBox(spotOf(seat), w, seat === 0);
    };

    it("a tapped home and a figure stepped out of its covered zone never overlap (tap 295,148, cover 0,40 250×225)", async () => {
      await render(state());
      tap(felt(), 295, 148);
      await advance(2000);
      const cover: Rect = { x: 0, y: 40, w: 250, h: 225 };
      rects["trick-play"] = cover;
      await render(state({ trick: { leader: 1, plays: [{ seat: 1, cards: ["HA"] }] } } as Partial<GameState>));
      await advance(2000);
      for (const seat of [0, 1]) expect(host.querySelector(`.tc-seat[data-seat="${seat}"]`), `seat ${seat}`).not.toBeNull();
      expect(meets(figure(0), figure(1))).toBe(false);
      for (const seat of [0, 1, 2, 3]) {
        expect(meets(figure(seat), cover), `seat ${seat}`).toBe(false);
        for (const other of [0, 1, 2, 3]) if (other > seat) expect(meets(figure(seat), figure(other)), `${seat}/${other}`).toBe(false);
      }
    });

    it("yours stepped out of a covered zone still takes a tap on clear felt (cover 0,40 250×225, tap 580,190)", async () => {
      await render(state());
      rects["trick-play"] = { x: 0, y: 40, w: 250, h: 225 };
      await render(state({ trick: { leader: 1, plays: [{ seat: 1, cards: ["HA"] }] } } as Partial<GameState>));
      await advance(2000);
      expect(host.querySelector('.tc-seat[data-seat="0"]')).not.toBeNull();
      const before = walks("0").length;
      tap(felt(), 580, 190);
      expect(walks("0").length).toBe(before + 1);
      await advance(2000);
      const at = spotOf(0);
      expect(Math.hypot(at.x + 22 - 580, at.y + 44 - 190)).toBeLessThan(80);
    });

    // a flight drawn as `matrix(a, b, c, d, tx, ty)` about the wrapper's centre, from where it lands (`r`)
    const drawnAs = (r: Rect, k: [number, number, number, number, number, number], centre: { x: number; y: number }): Rect => {
      const [a, b, c, d, tx, ty] = k;
      const pts = [[r.x, r.y], [r.x + r.w, r.y], [r.x, r.y + r.h], [r.x + r.w, r.y + r.h]].map(([x, y]) => {
        const vx = x - centre.x, vy = y - centre.y;
        return [centre.x + a * vx + c * vy + tx, centre.y + b * vx + d * vy + ty];
      });
      const xs = pts.map((q) => q[0]), ys = pts.map((q) => q[1]);
      return { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
    };
    const turn = (deg: number, tx: number, ty: number, k = 1): [number, number, number, number, number, number] => {
      const r = (deg * Math.PI) / 180;
      return [k * Math.cos(r), k * Math.sin(r), -k * Math.sin(r), k * Math.cos(r), tx, ty];
    };
    for (const [name, k] of [
      ["half size, 120 px above", [0.5, 0, 0, 0.5, 0, -120]],
      ["turned 30° at 0.4, moved", turn(30, 40, -100, 0.4)],
      ["turned −15° at 0.5, moved", turn(-15, -60, 80, 0.5)],
    ] as const) {
      it(`cards flying in (${name}) are measured where they land, their label too: the companion there clears both`, async () => {
        await render(state());
        const was = spotOf(1);
        // the final 93×82 card box and its LEAD label under it, over the left seat's companion
        const card: Rect = { x: was.x + 10, y: was.y - 20, w: 93, h: 82 };
        const label: Rect = { x: card.x + 20, y: card.y + card.h + 4, w: 52, h: 19 };
        const wrap: Rect = { x: card.x, y: card.y, w: 93, h: 105 };
        const centre = { x: wrap.x + wrap.w / 2, y: wrap.y + wrap.h / 2 };
        const el = host.querySelector(".trick-play") as HTMLElement;
        el.style.transform = `matrix(${k.join(", ")})`;
        Object.defineProperty(el, "offsetWidth", { configurable: true, value: wrap.w });
        Object.defineProperty(el, "offsetHeight", { configurable: true, value: wrap.h });
        const tag = document.createElement("div");
        tag.className = "trick-tag";
        el.appendChild(tag);
        rects["trick-play"] = drawnAs(wrap, k as never, centre);
        rects["trick-tag"] = drawnAs(label, k as never, centre);
        await render(state({ trick: { leader: 1, plays: [{ seat: 1, cards: ["HA"] }] } } as Partial<GameState>));
        await advance(1000);
        expect(meets(figure(1), card), "card").toBe(false);
        expect(meets(figure(1), label), "label").toBe(false);
        tag.remove();
      });
    }

    it("a new table forgets the tapped spot: yours goes back by your hand", async () => {
      await render(state({ room: "A" } as Partial<GameState>));
      const home = spotOf(0);
      tap(felt(), 420, 220);
      await advance(2000);
      expect(near(spotOf(0), home)).toBeGreaterThan(100);
      await render(state({ room: "B" } as Partial<GameState>));
      await advance(2000);
      expect(near(spotOf(0), home)).toBeLessThanOrEqual(22);
    });

    it("cards covering the tapped spot send yours on a quick hop to the nearest clear spot, its home from then on", async () => {
      await render(state());
      const home = spotOf(0);
      tap(felt(), 420, 220);
      await advance(2000);
      const end = spotOf(0);
      rects["trick-play"] = { x: end.x + 4, y: end.y + 10, w: 24, h: 24 };
      const before = walks("0").length;
      await render(state({ trick: { leader: 1, plays: [{ seat: 1, cards: ["HA"] }] } } as Partial<GameState>));
      const hop = walks("0").slice(before);
      expect(hop).toHaveLength(1);
      expect(hop[0].ms).toBeLessThanOrEqual(500);
      const adopted = spotOf(0);
      expect(clear(adopted, 44, true, layout())).toBe(true);
      expect(clear(end, 44, true, layout())).toBe(false);
      // the nearest clear spot, not the old home by your hand
      expect(near(adopted, end)).toBeLessThan(60);
      expect(near(adopted, home)).toBeGreaterThan(100);
      const taken = walks("0").length;
      cycle([0.05, 0.95, 0.3, 0.7]);
      for (let t = 0; t < 30000; t += 1000) await advance(1000);
      const after = stops(taken);
      expect(after.length).toBeGreaterThanOrEqual(2);
      for (const s of after) {
        expect(near(s, adopted)).toBeLessThanOrEqual(44);
        expect(clear(s, 44, true, layout())).toBe(true);
      }
    });

    it("a tap on a card, a button or another control is not a tap on the felt", async () => {
      await render(state());
      for (const sel of [".hand-slot", ".trick-play", ".opponent"]) tap(host.querySelector(sel)!, 300, 300);
      const b = document.createElement("button");
      felt().appendChild(b);
      tap(b, 400, 200);
      expect(walks("0")).toHaveLength(0);
    });

    it("taps on the felt are throttled", async () => {
      await render(state());
      tap(felt(), 420, 220);
      act(() => { vi.advanceTimersByTime(100); });
      tap(felt(), 300, 230);
      expect(walks("0")).toHaveLength(1);
      act(() => { vi.advanceTimersByTime(600); });
      tap(felt(), 300, 230);
      expect(walks("0")).toHaveLength(2);
    });

    // the special is the drawing's own signature, animated (not the still peak)
    const specialOn = (seat: string) => {
      const svg = host.querySelector(`.tc-seat[data-seat="${seat}"] svg`)!;
      return svg.classList.contains("cmp-react") && !svg.classList.contains("cmp-rest");
    };

    it("a tap on your own companion plays its special, at most once every 3 s, and does not walk it", async () => {
      await render(state());
      const mine = () => host.querySelector('.tc-seat[data-seat="0"] .tc-walk')!;
      tap(mine(), 0, 0);
      expect(host.querySelector('.tc-seat[data-seat="0"] .tc-move')!.getAttribute("data-move")).toBe("react");
      expect(specialOn("0")).toBe(true);
      expect(walks("0")).toHaveLength(0);
      // it plays for its own length (the Bun's steam puff), then stands still again
      await advance(1600);
      expect(specialOn("0")).toBe(false);
      tap(mine(), 0, 0);
      expect(specialOn("0")).toBe(false);
      await advance(1500);
      tap(mine(), 0, 0);
      expect(specialOn("0")).toBe(true);
      // another seat's companion takes no tap
      tap(host.querySelector('.tc-seat[data-seat="2"] .tc-walk')!, 0, 0);
      expect(specialOn("2")).toBe(false);
    });

    it.each([["lamb/newyear", 2600], ["panda/classic", 1900], ["bun/plain", 1540]] as const)(
      "a tap on yours as %s holds its special for the drawing's whole length (%i ms), from the one timing table", async (look, ms) => {
        await render(state({ players: [player(0, { look }), player(1), player(2), player(3)] } as Partial<GameState>));
        expect(DRAWINGS[look.split("/")[0] as keyof typeof DRAWINGS].reactMs).toBe(ms);
        tap(host.querySelector('.tc-seat[data-seat="0"] .tc-walk')!, 0, 0);
        expect(specialOn("0")).toBe(true);
        await advance(ms - 50);
        expect(specialOn("0")).toBe(true);
        await advance(100);
        expect(specialOn("0")).toBe(false);
      });

    it("your team's round win plays each of its companions' special once the round-end sheet closes", async () => {
      await render(state());
      const won = { winner_team: 0, level_change: 0, new_levels: ["2", "A"] };
      await render(state({ phase: "round_end", round_result: won } as unknown as Partial<GameState>));
      act(() => { vi.advanceTimersByTime(3000); });
      expect([...moves("0"), ...moves("2")]).toHaveLength(0);
      await render(state({ phase: "deal" } as unknown as Partial<GameState>));
      expect(["0", "1", "2", "3"].map((s) => host.querySelector(`.tc-seat[data-seat="${s}"] .tc-move`)!.getAttribute("data-move")))
        .toEqual(["react", "idle", "react", "idle"]);
    });

    it("a round won with a level gained pops the level first, then the special", async () => {
      await render(state());
      const won = { winner_team: 0, level_change: 2, new_levels: ["4", "A"] };
      await render(state({ phase: "round_end", levels: ["4", "A"], round_result: won } as unknown as Partial<GameState>));
      await render(state({ phase: "deal", levels: ["4", "A"] } as unknown as Partial<GameState>));
      expect(moves("0").map((a) => a.move)).toEqual(["levelup"]);
      expect(specialOn("0")).toBe(false);
      await advance(LEVEL_UP_MS + 20);
      expect(moves("0").map((a) => a.move)).toEqual(["levelup"]);
      expect(specialOn("0")).toBe(true);
    });

    it("a tap is taken once: moved off and on again, yours never replays an old tap over a companion that has arrived", async () => {
      const bots = [player(0), player(1, { is_bot: true, look: null }), player(2, { is_bot: true, look: null }), player(3, { is_bot: true, look: null })];
      await render(state({ players: bots } as Partial<GameState>));
      // a tap where the left seat's companion will stand once a person sits there
      tap(felt(), 124 + 22, 118 + 44);
      expect(walks("0")).toHaveLength(1);
      const tapped = walks("0")[0].frames[1].transform;
      // cards cover the tapped spot and your corner: yours hops to the nearest clear spot
      rects["trick-play"] = { x: 0, y: 40, w: 340, h: 225 };
      await render(state({ players: bots, trick: { leader: 1, plays: [{ seat: 1, cards: ["HA"] }] } } as Partial<GameState>));
      expect(clear(spotOf(0), 44, true, layout())).toBe(true);
      // the cards clear and a person takes the left seat
      rects["trick-play"] = { x: 0, y: 0, w: 0, h: 0 };
      const people = [player(0), player(1), player(2, { is_bot: true, look: null }), player(3, { is_bot: true, look: null })];
      await render(state({ players: people, trick: { leader: 2, plays: [] } } as Partial<GameState>));
      await advance(50);
      const mine = spotOf(0);
      const theirs = spotOf(1);
      const w1 = Number(host.querySelector('.tc-seat[data-seat="1"] svg')!.getAttribute("width"));
      expect(meets(figureBox(mine, 44, true), figureBox(theirs, w1, false))).toBe(false);
      // no later walk goes back to the old tap's spot
      expect(walks("0").slice(1).map((w) => w.frames[1].transform)).not.toContain(tapped);
    });

    it("under Reduce Motion a tap on the felt leaves your companion at home", async () => {
      const mm = window.matchMedia;
      window.matchMedia = ((q: string) => ({ matches: q.includes("reduce"), addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
      try {
        await render(state());
        const home = spotOf(0);
        tap(felt(), 420, 220);
        expect(walks("0")).toHaveLength(0);
        expect(spotOf(0)).toEqual(home);
        await advance(20000);
        expect(spotOf(0)).toEqual(home);
      } finally {
        window.matchMedia = mm;
      }
    });

    it("a tap on another companion's spot sends yours beside it, never over it", async () => {
      await render(state());
      const left = host.querySelector('.tc-seat[data-seat="1"] svg')!;
      const at = spotOf(1);
      const w = Number(left.getAttribute("width"));
      tap(felt(), at.x + w / 2, at.y + w);
      expect(walks("0")).toHaveLength(1);
      const end = spotOf(0);
      expect(meets(figureBox(end, 44, true), figureBox(at, w, false))).toBe(false);
    });

    it("under Reduce Motion a tap on your companion shows its special's still peak, no animation", async () => {
      const mm = window.matchMedia;
      window.matchMedia = ((q: string) => ({ matches: q.includes("reduce"), addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
      try {
        await render(state());
        tap(host.querySelector('.tc-seat[data-seat="0"] .tc-walk')!, 0, 0);
        const svg = host.querySelector('.tc-seat[data-seat="0"] svg')!;
        expect(host.querySelector('.tc-seat[data-seat="0"] .tc-move')!.getAttribute("data-move")).toBe("react");
        // the peak drawn still: no pose class to animate it
        expect(svg.classList.contains("cmp-react")).toBe(false);
        expect(moves("0")).toHaveLength(0);
        await advance(1100);
        expect(host.querySelector('.tc-seat[data-seat="0"] .tc-move')!.getAttribute("data-move")).toBe("idle");
      } finally {
        window.matchMedia = mm;
      }
    });

    it("cards landing on a companion's spot send it on a quick hop-walk from where it stands, never a jump", async () => {
      await render(state());
      const was = spotOf(1);
      rects["trick-play"] = { x: was.x + 4, y: was.y + 10, w: 24, h: 24 };
      await render(state({ trick: { leader: 1, plays: [{ seat: 1, cards: ["HA"] }] } } as Partial<GameState>));
      const step = walks("1");
      expect(step).toHaveLength(1);
      expect(step[0].frames[0].transform).toBe(`translate(${was.x}px, ${was.y}px)`);
      expect(step[0].ms).toBeGreaterThanOrEqual(300);
      expect(step[0].ms).toBeLessThanOrEqual(500);
      const now = spotOf(1);
      expect(step[0].frames[1].transform).toBe(`translate(${now.x}px, ${now.y}px)`);
      expect(now).not.toEqual(was);
    });

    it("a walk cut short goes on from where it is drawn, not from its start or its end", async () => {
      await render(state());
      tap(felt(), 420, 220);
      expect(walks("0")).toHaveLength(1);
      const dest = spotOf(0);
      // mid-walk, the figure is drawn part of the way there
      const css = vi.spyOn(window, "getComputedStyle").mockImplementation(((el: Element) =>
        ({ transform: el.classList.contains("tc-walk") ? "matrix(1, 0, 0, 1, 111, 222)" : "none" } as CSSStyleDeclaration)) as typeof window.getComputedStyle);
      try {
        rects["trick-play"] = { x: dest.x + 4, y: dest.y + 10, w: 24, h: 24 };
        await render(state({ trick: { leader: 1, plays: [{ seat: 1, cards: ["HA"] }] } } as Partial<GameState>));
      } finally {
        css.mockRestore();
      }
      const ws = walks("0");
      expect(ws).toHaveLength(2);
      expect(ws[0].cancel).toHaveBeenCalled();
      expect(ws[1].frames[0].transform).toBe("translate(111px, 222px)");
    });

    it("a walk a tap sent is an unhurried stroll (about 0.5 s a figure's width, 1.2 to 3 s, a slower step); idle walks keep their pace", async () => {
      await render(state());
      const from = spotOf(0);
      tap(felt(), 420, 220);
      const [w] = walks("0");
      const to = spotOf(0);
      const figures = Math.hypot(to.x - from.x, to.y - from.y) / 44;
      expect(w.ms).toBe(Math.min(TAP_WALK_MS[1], Math.max(TAP_WALK_MS[0], figures * 500)));
      expect(w.ms).toBeGreaterThan(1500);
      // the gait's step slowed to match: 520 ms a hop, so the feet keep up with the ground
      const gait = anims.find((a) => a.seat === "0" && a.box === "tc-face")!;
      expect(gait.ms).toBe(520);
      // a short tap walk still takes 1.2 s at least
      await advance(3500);
      const here = spotOf(0);
      tap(felt(), here.x + 22 + 30, here.y + 44);
      const short = walks("0").at(-1)!;
      expect(short.ms).toBe(TAP_WALK_MS[0]);
      // an idle walk keeps its own pace (0.8 to 1.5 s)
      const n = walks("0").length;
      await advance(16000);
      const idle = walks("0").slice(n);
      expect(idle.length).toBeGreaterThan(0);
      for (const iw of idle) expect(iw.ms).toBeLessThanOrEqual(1500);
    });

    it("a second tap mid-stroll turns it from where it is drawn", async () => {
      await render(state());
      tap(felt(), 420, 220);
      await advance(600);
      const css = vi.spyOn(window, "getComputedStyle").mockImplementation(((el: Element) =>
        ({ transform: el.classList.contains("tc-walk") ? "matrix(1, 0, 0, 1, 150, 190)" : "none" } as CSSStyleDeclaration)) as typeof window.getComputedStyle);
      try {
        tap(felt(), 600, 200);
      } finally {
        css.mockRestore();
      }
      const ws = walks("0");
      expect(ws).toHaveLength(2);
      expect(ws[0].cancel).toHaveBeenCalled();
      expect(ws[1].frames[0].transform).toBe("translate(150px, 190px)");
    });

    it("at rest each companion fidgets in turn: a sway, a blink, a small hop", async () => {
      await render(state());
      const seen: string[] = [];
      let blinking = false;
      for (let t = 0; t < 40000 && seen.length < 3; t += 50) {
        act(() => { vi.advanceTimersByTime(50); });
        const fid = moves("1").filter((a) => a.move === "idle");
        const shut = host.querySelector('.tc-seat[data-seat="1"] svg')!.classList.contains("cmp-blink");
        if (shut && !blinking) seen.push("blink");
        blinking = shut;
        while (fid.length > seen.filter((k) => k !== "blink").length) {
          const f = fid[seen.filter((k) => k !== "blink").length];
          seen.push(/rotate/.test(String(f.frames[1]?.transform)) ? "sway" : /translateY/.test(String(f.frames[1]?.transform)) ? "hop" : "?");
        }
      }
      expect(seen).toEqual(["sway", "blink", "hop"]);
    });
  });

  it("a line that appears over your companion (a hint once a card is chosen) moves it off", async () => {
    await draw(table(state()));
    const was = spotOf(0);
    const line = document.createElement("div");
    line.className = "hand-line";
    rects["hand-line"] = { x: was.x + 4, y: was.y + 10, w: 24, h: 24 };
    await act(async () => {
      host.querySelector(".felt")!.appendChild(line);
      await new Promise((r) => setTimeout(r, 60));
    });
    await act(async () => { await new Promise((r) => setTimeout(r, 60)); });
    const now = spotOf(0);
    expect(now).not.toEqual(was);
    expect(clear(now, 44, true, { ...layout(), obstacles: [...layout().obstacles, rects["hand-line"]] })).toBe(true);
  });

  it("under Reduce Motion it stands on its home and never walks", async () => {
    vi.useFakeTimers();
    const mm = window.matchMedia;
    window.matchMedia = ((q: string) => ({ matches: q.includes("reduce"), addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
    const proto = Element.prototype as unknown as { animate?: unknown };
    const had = proto.animate;
    const calls: Element[] = [];
    proto.animate = function (this: Element) { calls.push(this); return { finished: new Promise(() => {}), cancel: () => {} }; };
    try {
      await act(async () => { root.render(table(state())); });
      const home = spotOf(2);
      act(() => { vi.advanceTimersByTime(60000); });
      expect(calls).toHaveLength(0);
      expect(spotOf(2)).toEqual(home);
    } finally {
      proto.animate = had;
      window.matchMedia = mm;
      vi.useRealTimers();
    }
  });
});
