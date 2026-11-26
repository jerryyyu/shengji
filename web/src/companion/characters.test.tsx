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
import { COMPANIONS, COMPANION_KINDS, lookCatalogue, parseLook } from "./look";
import { companionSize, levelScale } from "./rig";
import { parseArt } from "./Tractor";
import TableCompanions, { SEAT_SIZE, levelIndex } from "./TableCompanions";
import { clear } from "./seatZones";
import type { Layout, Rect } from "./seatZones";
import { TABLES } from "./seatZones.fixtures";
import CollectionPage from "../components/CollectionPage";
import { forgetHomeSession } from "../home/session";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
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
    expect(COMPANION_KINDS).toEqual(["tractor", "bun", "chick", "sparrow"]);
    expect(COMPANIONS.bun).toEqual(["plain", "custard", "taro", "peach"]);
    expect(COMPANIONS.chick).toEqual(["yellow", "cream", "cocoa", "ink"]);
    expect(COMPANIONS.sparrow).toEqual(["tree", "java", "snow", "oriole"]);
    expect(parseLook("chick/ink")).toEqual({ kind: "chick", colour: "ink" });
    // a colour of another companion, or one not drawn here, is the default
    for (const bad of ["bun/red", "sparrow/plain", "lamb/newyear", "chick/ink/x"]) {
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
    for (const kind of COMPANION_KINDS) {
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
    expect(urls.size).toBe(COMPANION_KINDS.reduce((n, k) => n + COMPANIONS[k].length, 0));
  });

  it("the Tractor carries its rider, in its portrait too", () => {
    const tractor = DRAWINGS.tractor.markup("red", "t", { pose: "idle" });
    expect(tractor).toContain('class="cmp-rider"');
    expect(decodeURIComponent(DRAWINGS.tractor.portraitUrl("red", false))).toContain("cmp-rider");
  });

  it("at the table a team stands on its own pad shape and wears its colour", () => {
    for (const kind of COMPANION_KINDS) {
      const us = DRAWINGS[kind].markup(COMPANIONS[kind][0], "t", { team: "us" });
      const them = DRAWINGS[kind].markup(COMPANIONS[kind][0], "t", { team: "them" });
      expect(us).toContain('class="cmp-pad"');
      expect(us).toMatch(/<g class="cmp-pad"><ellipse/);
      expect(them).toMatch(/<g class="cmp-pad"><path/);
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
  it("grows 2.5% a level to 1.3 times at A, never past the seat cap", () => {
    expect(levelScale(0)).toBe(1);
    expect(levelScale(12)).toBeCloseTo(1.3);
    expect(levelScale(40)).toBeCloseTo(1.3);
    expect(levelIndex("2")).toBe(0);
    expect(levelIndex("A")).toBe(12);
    expect(levelIndex(undefined)).toBe(0);
    const { phone, tablet } = SEAT_SIZE;
    expect(companionSize(phone.base, 0, phone.max)).toBe(32);
    expect(companionSize(phone.base, 12, phone.max)).toBe(40);
    expect(companionSize(tablet.base, 0, tablet.max)).toBe(44);
    expect(companionSize(tablet.base, 12, tablet.max)).toBe(56);
  });

  it("a level gained pops the figure from its old size; a level lost does not", async () => {
    await draw(<Companion kind="chick" colour="yellow" size={44} max={56} level={0} team="us" />);
    const svg = () => host.querySelector("svg.cmp") as SVGSVGElement;
    expect(svg().getAttribute("width")).toBe("44");
    expect(svg().classList.contains("cmp-grow")).toBe(false);
    await draw(<Companion kind="chick" colour="yellow" size={44} max={56} level={4} team="us" />);
    expect(svg().getAttribute("width")).toBe("48");
    expect(svg().classList.contains("cmp-grow")).toBe(true);
    expect(svg().style.getPropertyValue("--cmp-from")).toBe((44 / 48).toFixed(3));
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

describe("the Collection, one page", () => {
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
  const tile = (name: string) => [...host.querySelectorAll<HTMLButtonElement>(".coll-kind")]
    .find((b) => b.querySelector(".coll-kind-name")!.textContent === name)!;
  const signedIn = () => { authState.current = { status: "in", clientId: "cid", user }; };
  const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

  it("lists the four companions and ticks the one in use; a tap on one only shows it", async () => {
    signedIn();
    await draw(<CollectionPage />);
    const tiles = [...host.querySelectorAll<HTMLButtonElement>(".coll-kind")];
    expect(tiles.map((b) => b.querySelector(".coll-kind-name")!.textContent)).toEqual(["Tractor", "Bun", "Chick", "Sparrow"]);
    expect(tiles.filter((b) => b.querySelector(".coll-tick")).map((b) => b.querySelector(".coll-kind-name")!.textContent)).toEqual(["Bun"]);
    await act(async () => { tile("Chick").click(); });
    await settle();
    expect(puts).toEqual([]);
    expect(tile("Chick").classList.contains("on")).toBe(true);
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
    await act(async () => { tile("Tractor").click(); });
    await act(async () => { swatch("Imperial yellow").click(); });
    expect(use()?.textContent).toBe("Play 10 rounds to unlock · 3 of 10");
    expect(use()?.disabled).toBe(true);
    await act(async () => { swatch("Ink black").click(); });
    expect(use()?.textContent).toBe("Win a ranked game to unlock");
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
    expect(use()?.textContent).toBe("Sign in to use");
    await act(async () => { tile("Tractor").click(); });
    await act(async () => { swatch("Lantern orange").click(); });
    expect(use()?.textContent).toBe("Sign in to use");
    expect(host.textContent).not.toMatch(/of 25|rounds/);
    expect(swatch("Lantern orange").getAttribute("aria-label")).toBe("Lantern orange");
  });

  it("has no state chips, only Try on your table, which stands it beside a partner on your team's pads", async () => {
    signedIn();
    await draw(<CollectionPage />);
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
      const pose = () => [...host.querySelector(".char-stage svg.cmp")!.classList].find((c) => /^cmp-(idle|hop|cheer|sleep|react)$/.test(c));
      expect(pose()).toBe("cmp-idle");
      act(() => { vi.advanceTimersByTime(2300); });
      expect(pose()).toBe("cmp-hop");
    } finally {
      vi.useRealTimers();
    }
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
              "you-row": m.row!, hand: m.hand, "trick-play": { x: 0, y: 0, w: 0, h: 0 } };
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
      <div className="you-row" /><div className="hand" />
      <TableCompanions state={s} />
    </div>
  );
  const spotOf = (seat: number) => {
    const w = host.querySelector<HTMLElement>(`.tc-seat[data-seat="${seat}"] .tc-walk`)!;
    const [x, y] = /translate\(([-\d.]+)px, ([-\d.]+)px\)/.exec(w.style.transform)!.slice(1).map(Number);
    return { x, y };
  };
  const layout = (): Layout => ({ felt: m.felt, plates: m.plates, tagline: null, row: m.row,
    obstacles: [rects["trick-play"], m.hand, ...Object.values(m.plates)].filter((r) => r.w > 0) });

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

  it("a team that climbs at round end cheers and grows", async () => {
    await draw(table(state()));
    const result = { winner_team: 0, level_change: 2, new_levels: ["4", "A"] };
    await draw(table(state({ phase: "round_end", levels: ["4", "A"], round_result: result } as unknown as Partial<GameState>)));
    expect([0, 2].map((s) => host.querySelector(`.tc-seat[data-seat="${s}"] .tc-move`)!.getAttribute("data-move"))).toEqual(["cheer", "cheer"]);
    expect([0, 2].every((s) => host.querySelector(`.tc-seat[data-seat="${s}"] svg`)!.classList.contains("cmp-grow"))).toBe(true);
  });

  it("is the default: each person's companion stands by their nameplate, small, clear of the table, yours tagged You", async () => {
    await draw(table(state()));
    const seats = [...host.querySelectorAll(".tc-seat")];
    expect(seats.map((s) => [s.getAttribute("data-seat"), s.getAttribute("data-pos")])).toEqual([
      ["0", "bottom"], ["1", "left"], ["2", "top"], ["3", "right"]]);
    expect([...host.querySelectorAll(".tc-you")].map((t) => t.closest(".tc-seat")!.getAttribute("data-seat"))).toEqual(["0"]);
    for (const s of [0, 1, 2, 3]) {
      const svg = host.querySelector(`.tc-seat[data-seat="${s}"] svg`)!;
      expect(Number(svg.getAttribute("width"))).toBeLessThanOrEqual(40);
      expect(clear(spotOf(s), Number(svg.getAttribute("width")), s === 0, layout())).toBe(true);
    }
    // each stands under or beside its own nameplate
    const near = (s: number, plate: Rect) => Math.hypot(spotOf(s).x - plate.x, spotOf(s).y - plate.y) < 120;
    expect(near(1, m.plates.left) && near(2, m.plates.top) && near(3, m.plates.right)).toBe(true);
  });

  it("grows by level within the seat cap", async () => {
    await draw(table(state()));
    expect(host.querySelector('.tc-seat[data-seat="0"] svg')!.getAttribute("width")).toBe("32");
    expect(host.querySelector('.tc-seat[data-seat="1"] svg')!.getAttribute("width")).toBe("40");
  });

  it("walks now and then within its zone, facing the way it goes, and never while hidden", async () => {
    vi.useFakeTimers();
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
      expect(clear(end, 40, false, layout())).toBe(true);
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
    expect(clear(now, 40, false, layout())).toBe(true);
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
