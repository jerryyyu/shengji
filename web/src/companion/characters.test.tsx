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
import TableCompanions, { TABLE_SIZE, levelIndex } from "./TableCompanions";
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
    const { phone, tablet } = TABLE_SIZE;
    expect(companionSize(phone.base, 0, phone.max)).toBe(44);
    expect(companionSize(phone.base, 12, phone.max)).toBe(56);
    expect(companionSize(tablet.base, 0, tablet.max)).toBe(56);
    expect(companionSize(tablet.base, 12, tablet.max)).toBe(72);
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

describe("the character page", () => {
  const user: AuthUser = {
    name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry",
    rounds_played: 14, ranked_wins: 0, look: "bun/custard", companions: "team", features: { collection: true },
  };
  beforeEach(() => {
    globalThis.fetch = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes("/api/leaderboard")) return { status: 200, json: async () => ({ players: [], me: null }) } as Response;
      const body = JSON.parse(String(init?.body ?? "{}"));
      return { status: 200, json: async () => ({ ...user, ...body }) } as Response;
    }) as unknown as typeof fetch;
  });
  const foot = () => host.querySelector(".char-foot") as HTMLButtonElement | null;
  const swatch = (label: string) => [...host.querySelectorAll<HTMLButtonElement>(".char-swatches .coll-swatch")]
    .find((s) => s.getAttribute("aria-label")!.startsWith(label))!;

  it("the Collection lists the four companions and a tap opens one's page", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw(<CollectionPage />);
    const tiles = [...host.querySelectorAll<HTMLButtonElement>(".coll-kind")];
    expect(tiles.map((b) => b.textContent)).toEqual(["Tractor", "Bun", "Chick", "Sparrow"]);
    expect(tiles.filter((b) => b.classList.contains("on")).map((b) => b.textContent)).toEqual(["Bun"]);
    // the colours under the felt are the worn companion's
    expect(host.querySelectorAll(".coll-swatches .coll-swatch")).toHaveLength(4);
    await act(async () => { tiles[2].click(); });
    expect(window.location.hash).toBe("#/collection/chick");
  });

  it("shows the worn colour as Equipped, another as Equip, and its states with the signature", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw(<CollectionPage kind="bun" />);
    expect(host.querySelector(".large-title")?.textContent).toBe("Bun");
    expect([...host.querySelectorAll(".char-chip")].map((b) => b.textContent))
      .toEqual(["Idle", "Hop", "Cheer", "Sleep", "Steam puff", "Try on your table"]);
    expect(foot()?.textContent).toBe("Equipped");
    expect(foot()?.disabled).toBe(true);
    expect(host.querySelector(".char-status")?.textContent).toBe("Custard");
    await act(async () => { swatch("Taro").click(); });
    expect(foot()?.textContent).toBe("Equip");
    expect(host.querySelector(".char-status")?.textContent).toBe("Taro");
    await act(async () => { foot()!.click(); await new Promise((r) => setTimeout(r, 0)); });
    const put = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find((c) => c[0] === "/api/me/look")!;
    expect(JSON.parse(String(put[1].body))).toEqual({ look: "bun/taro" });
  });

  it("a locked Tractor colour has its unlock line in the foot's place", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw(<CollectionPage kind="tractor" />);
    await act(async () => { swatch("Jade").click(); });
    expect(foot()).toBeNull();
    expect(host.querySelector(".char-status")?.textContent).toBe("Jade, 14 of 50 rounds");
  });

  it("a try-on stands it beside a partner on your team's pads", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw(<CollectionPage kind="sparrow" />);
    const chip = [...host.querySelectorAll<HTMLButtonElement>(".char-chip")].find((b) => b.textContent === "Try on your table")!;
    await act(async () => { chip.click(); });
    const figs = [...host.querySelectorAll(".char-stage svg.cmp")];
    expect(figs.map((f) => [...f.classList].filter((c) => /^cmp-(sparrow|tractor|us)$/.test(c)))).toEqual([
      ["cmp-sparrow", "cmp-us"], ["cmp-tractor", "cmp-us"]]);
    expect(chip.getAttribute("aria-pressed")).toBe("true");
  });

  it("a guest sees every page with no foot to press", async () => {
    await draw(<CollectionPage kind="chick" />);
    expect(host.querySelector(".char-stage svg.cmp-chick")).not.toBeNull();
    expect(foot()).toBeNull();
  });

  it("an unknown companion in the URL opens the Collection", async () => {
    await draw(<CollectionPage kind="lamb" />);
    expect(host.querySelector(".large-title")?.textContent).toBe("Collection");
  });
});

describe("the table, in Team view", () => {
  const player = (seat: number, over: Partial<StatePlayer> = {}): StatePlayer => ({
    seat, name: `P${seat}`, is_bot: false, look: ["bun/plain", "sparrow/tree", "chick/yellow", "tractor/red"][seat],
    connected: true, team: (seat % 2) as 0 | 1, cards_left: 25, is_banker: false, takeover_in: null,
    controller: "human", reserved_for: null, reserved_secs: null, ...over,
  });
  const state = (over: Partial<GameState> = {}): GameState => ({
    you: 0, phase: "play", levels: ["2", "A"], players: [player(0), player(1), player(2), player(3, { is_bot: true, look: null })],
    last_trick: null, round_result: null, ...over,
  } as unknown as GameState);
  const shownTo = () => { authState.current = { status: "out", clientId: "cid", user: null, collection: true } as AuthState; };

  it("stands each team's people together, yours on discs and theirs on diamonds, grown by level; a bot has none", async () => {
    shownTo();
    await draw(<TableCompanions state={state()} />);
    const us = host.querySelector(".tc-us")!;
    const them = host.querySelector(".tc-them")!;
    expect([...us.querySelectorAll(".tc-fig")].map((f) => f.getAttribute("data-seat"))).toEqual(["0", "2"]);
    expect([...them.querySelectorAll(".tc-fig")].map((f) => f.getAttribute("data-seat"))).toEqual(["1"]);
    expect([...us.querySelectorAll("svg")].every((s) => s.classList.contains("cmp-us") && s.getAttribute("width") === "44")).toBe(true);
    expect(them.querySelector("svg")!.classList.contains("cmp-them")).toBe(true);
    expect(them.querySelector("svg")!.getAttribute("width")).toBe("56");
    // your partner faces you; theirs face the table
    expect([...us.querySelectorAll(".tc-fig")].map((f) => f.classList.contains("tc-flip"))).toEqual([false, true]);
    expect(them.querySelector(".tc-fig")!.classList.contains("tc-flip")).toBe(true);
  });

  it("draws nothing unless the Collection is shown and the mode is Team", async () => {
    await draw(<TableCompanions state={state()} />);
    expect(host.querySelector(".table-companions")).toBeNull();
    shownTo();
    window.localStorage.setItem("shengji.companions", "off");
    await draw(<TableCompanions state={state()} />);
    expect(host.querySelector(".table-companions")).toBeNull();
  });

  it("a team hops for a trick it takes and cheers for one worth 10 or more; an absent person's companion sleeps", async () => {
    shownTo();
    await draw(<TableCompanions state={state()} />);
    const fig = (seat: number) => host.querySelector(`.tc-fig[data-seat="${seat}"] svg`)!;
    const players = [player(0), player(1, { connected: false }), player(2), player(3)];
    const small = { leader: 0, winner: 2, points: 5, plays: [{ seat: 0, cards: ["HA"] }] };
    await draw(<TableCompanions state={state({ last_trick: small, players } as Partial<GameState>)} />);
    const box = (seat: number) => host.querySelector(`.tc-fig[data-seat="${seat}"] .tc-move`)!;
    expect([box(0), box(2)].map((b) => b.getAttribute("data-move"))).toEqual(["hop", "hop"]);
    // the drawing stays still at the table: only its box moves
    expect([fig(0), fig(2)].every((f) => f.classList.contains("cmp-rest"))).toBe(true);
    expect(fig(1).classList.contains("cmp-sleep")).toBe(true);
    const big = { leader: 2, winner: 0, points: 10, plays: [{ seat: 2, cards: ["HK"] }] };
    await draw(<TableCompanions state={state({ last_trick: big, players } as Partial<GameState>)} />);
    expect([box(0), box(2)].map((b) => b.getAttribute("data-move"))).toEqual(["cheer", "cheer"]);
    // a cheer swaps in the cheer's peak, confetti and all
    expect([fig(0), fig(2)].every((f) => f.querySelector(".cmp-confetti") !== null)).toBe(true);
    const theirs = { leader: 1, winner: 1, points: 20, plays: [{ seat: 1, cards: ["SA"] }] };
    await draw(<TableCompanions state={state({ last_trick: theirs, players } as Partial<GameState>)} />);
    // the absent taker's companion sleeps through it
    expect(fig(1).classList.contains("cmp-sleep")).toBe(true);
  });

  it("at rest nothing loops; each companion fidgets once every 6 to 10 s as a Web Animation, and not while the page is hidden", async () => {
    vi.useFakeTimers();
    let hidden = false;
    const vis = vi.spyOn(document, "visibilityState", "get").mockImplementation(() => (hidden ? "hidden" : "visible"));
    const played: Element[] = [];
    const proto = Element.prototype as unknown as { animate?: unknown };
    const had = proto.animate;
    proto.animate = function (this: Element) {
      played.push(this);
      return { finished: new Promise(() => {}), cancel: () => {} };
    };
    try {
      shownTo();
      await act(async () => { root.render(<TableCompanions state={state()} />); });
      expect([...host.querySelectorAll(".tc-fig svg")].every((f) => f.classList.contains("cmp-rest"))).toBe(true);
      act(() => { vi.advanceTimersByTime(5900); });
      expect(played).toHaveLength(0);
      act(() => { vi.advanceTimersByTime(4200); });
      // by 10.1 s each seat has fidgeted once, on its box
      expect(played.map((e) => e.closest(".tc-fig")!.getAttribute("data-seat")).sort()).toEqual(["0", "1", "2"]);
      expect(played.every((e) => e.classList.contains("tc-move"))).toBe(true);
      hidden = true;
      act(() => { document.dispatchEvent(new Event("visibilitychange")); });
      const before = played.length;
      act(() => { vi.advanceTimersByTime(30000); });
      expect(played).toHaveLength(before);
    } finally {
      proto.animate = had;
      vis.mockRestore();
      vi.useRealTimers();
    }
  });

  it("Individual draws nothing until it is designed", async () => {
    shownTo();
    window.localStorage.setItem("shengji.companions", "individual");
    await draw(<TableCompanions state={state()} />);
    expect(host.querySelector(".table-companions")).toBeNull();
  });

  it("a team that climbs at round end cheers", async () => {
    shownTo();
    const before = state();
    await draw(<TableCompanions state={before} />);
    const result = { winner_team: 0, level_change: 2, new_levels: ["4", "A"] };
    await draw(<TableCompanions state={state({ phase: "round_end", levels: ["4", "A"], round_result: result } as unknown as Partial<GameState>)} />);
    expect([...host.querySelectorAll(".tc-us .tc-move")].map((b) => b.getAttribute("data-move"))).toEqual(["cheer", "cheer"]);
    expect([...host.querySelectorAll(".tc-us svg")].every((f) => f.classList.contains("cmp-grow"))).toBe(true);
  });
});
