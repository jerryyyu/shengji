// The table companions answer the game: yours gets ready as your turn
// arrives and settles as you play; each watches a card played; a big play
// (20 points or more, a tractor led, a kitty taken) is marked, with limits
// that keep any figure from doing too much; Reduce Motion gets held poses.
// The table is drawn with the phone's measured rects and a recorded
// `Element.animate` on a fake clock.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthState } from "../auth";
import type { GameState, StatePlayer, TrickPlay } from "../protocol";

const { authState } = vi.hoisted(() => ({
  authState: { current: { status: "out", clientId: "cid", user: null } as AuthState },
}));
vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));
vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return { ...real, useAuth: () => authState.current, auth: { updated: () => {}, get state() { return authState.current; } } };
});

import TableCompanions from "./TableCompanions";
import { FlairLayer } from "./flairLayer";
import type { Piece } from "./flair";
import type { Rect } from "./seatZones";
import { TABLES } from "./seatZones.fixtures";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const m = TABLES["phone-land-w2"];
const player = (seat: number, over: Partial<StatePlayer> = {}): StatePlayer => ({
  seat, name: `P${seat}`, is_bot: false, look: ["bun/plain", "sparrow/tree", "chick/yellow", "tractor/red"][seat],
  connected: true, team: (seat % 2) as 0 | 1, cards_left: 25, is_banker: false, takeover_in: null,
  controller: "human", reserved_for: null, reserved_secs: null, ...over,
});
const state = (over: Partial<GameState> = {}): GameState => ({
  you: 0, room: "R", phase: "play", levels: ["2", "2"], players: [player(0), player(1), player(2), player(3)], turn: 1, banker: 1,
  trick: { leader: 1, plays: [] }, last_trick: null, round_result: null, ...over,
} as unknown as GameState);

interface Rec { seat: string | null; box: string; frames: Keyframe[]; ms: number; iters: number; at: number; done: boolean; cancelled: boolean }
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let anims: Rec[];
let spy: ReturnType<typeof vi.spyOn>;
let rnd: ReturnType<typeof vi.spyOn>;
let had: unknown;
let reduced = false;
const realMatch = window.matchMedia;
const proto = Element.prototype as unknown as { animate?: unknown };
beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  try { window.localStorage.clear(); } catch { /* none */ }
  authState.current = { status: "out", clientId: "cid", user: null, collection: true } as AuthState;
  const rects: Record<string, Rect> = { felt: { x: 0, y: 0, ...m.felt }, "pos-left": m.plates.left!, "pos-top": m.plates.top!, "pos-right": m.plates.right!,
    "you-row": m.row!, hand: m.hand, "hand-slot": m.firstCard };
  spy = vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const k = Object.keys(rects).find((c) => this.classList.contains(c));
    const r = k ? rects[k] : { x: 0, y: 0, w: 0, h: 0 };
    return { left: r.x, top: r.y, width: r.w, height: r.h, right: r.x + r.w, bottom: r.y + r.h, x: r.x, y: r.y, toJSON: () => ({}) } as DOMRect;
  });
  vi.useFakeTimers();
  rnd = vi.spyOn(Math, "random").mockReturnValue(0.5);
  anims = [];
  had = proto.animate;
  proto.animate = function (this: Element, frames: Keyframe[], opts: KeyframeAnimationOptions) {
    let timer = 0;
    const rec: Rec = { seat: this.closest(".tc-seat")?.getAttribute("data-seat") ?? null, box: this.className.toString().split(" ")[0],
      frames, ms: Number(opts?.duration ?? 0), iters: Number(opts?.iterations ?? 1), at: Date.now(), done: false, cancelled: false };
    const finished = new Promise<void>((r) => { timer = window.setTimeout(() => { rec.done = true; r(); }, rec.ms * rec.iters); });
    anims.push(rec);
    return { finished, cancel: () => { window.clearTimeout(timer); if (!rec.done) rec.cancelled = true; rec.done = true; } };
  };
  reduced = false;
  window.matchMedia = ((q: string) => ({ matches: reduced && q.includes("reduce"), addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  proto.animate = had;
  window.matchMedia = realMatch;
  rnd.mockRestore();
  spy.mockRestore();
  vi.useRealTimers();
});

const table = (s: GameState) => (
  <div className="felt">
    <div className="opponent pos-left" /><div className="opponent pos-top" /><div className="opponent pos-right" />
    <div className="you-row" /><div className="hand"><div className="hand-slot" /></div>
    <TableCompanions state={s} />
  </div>
);
const render = async (s: GameState) => { await act(async () => { root.render(table(s)); }); };
const advance = async (ms: number) => {
  await act(async () => { vi.advanceTimersByTime(ms); for (let i = 0; i < 6; i++) await Promise.resolve(); });
  await act(async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); });
};
const el = (seat: number, part: "walk" | "face" | "move") => host.querySelector<HTMLElement>(`.tc-seat[data-seat="${seat}"] .tc-${part}`)!;
/** A figure's way in as it is first drawn: it fades up. Not one of the moves that answer the game. */
const isArrive = (a: Rec) => a.frames[0]?.opacity === 0;
const on = (seat: number, part: "walk" | "face" | "move", from = 0) => anims.slice(from).filter((a) => a.seat === String(seat) && a.box === `tc-${part}` && !isArrive(a));
const text = (a: Rec) => a.frames.map((k) => String(k.transform)).join(" | ");
/** The moves this file is about, by what their keyframes do. */
const isPerk = (a: Rec) => a.box === "tc-move" && /scale\(1\.17, 1\.17\)$/.test(text(a)) && /^translateY\(0%\) rotate\(0deg\) scale\(1, 1\)/.test(text(a));
const isBob = (a: Rec) => a.box === "tc-move" && a.ms === 420 && /^translateY\(0%\) rotate\(0deg\) scale\(1\.17, 1\.17\)/.test(text(a));
const isRelax = (a: Rec) => a.box === "tc-move" && a.ms === 320 && /scale\(1\.17, 1\.17\).*scale\(1, 1\)$/.test(text(a));
const isBig = (a: Rec) => a.box === "tc-move" && /translateY\(-36%\)/.test(text(a));
const isDroop = (a: Rec) => a.box === "tc-move" && /rotate\([246]deg\) scale\(1\.07, 0\.84\)/.test(text(a));
const isChug = (a: Rec) => a.box === "tc-move" && a.ms === 560 && (text(a).match(/translateY\(-1[28]%\)/g) ?? []).length === 2;
const isLook = (a: Rec) => a.box === "tc-face" && a.ms === 260;
const play = (seat: number, card: string, shape?: TrickPlay["shape"]): TrickPlay => ({ seat, cards: [card], ...(shape ? { shape } : {}) });
const taken = (winner: number, points: number, n = 0) => ({ leader: 1, winner, points, plays: [play(1, `H${n}`), play(2, "H5"), play(3, "H6"), play(0, "H7")] });

describe("ready on your turn", () => {
  it("as the turn comes to you yours jumps once and lands larger; nobody else's moves", async () => {
    await render(state());
    expect(anims.filter(isPerk)).toHaveLength(0);
    await render(state({ turn: 0 }));
    const perks = anims.filter(isPerk);
    expect(perks.map((a) => a.seat)).toEqual(["0"]);
    expect(perks[0].ms).toBe(520);
    // an anticipation squash, a jump of a tenth to a quarter of its height, then the larger size
    expect(text(perks[0])).toMatch(/scale\(1\.1, 0\.86\).*translateY\(-(26|18|10)%\)/);
    expect(el(0, "move").style.transform).toBe("scale(1.17)");
    expect(el(0, "walk").hasAttribute("data-ready")).toBe(true);
    for (const seat of [1, 2, 3]) {
      expect(on(seat, "move")).toHaveLength(0);
      expect(el(seat, "move").style.transform).toBe("");
    }
  });

  it("holds the larger size with three small bobs and then stands still: no loop runs while you think", async () => {
    await render(state());
    await render(state({ turn: 0 }));
    await advance(5000);
    const bobs = anims.filter(isBob);
    expect(bobs).toHaveLength(3);
    expect(bobs.every((b) => b.seat === "0" && b.iters === 1)).toBe(true);
    const from = anims.length;
    await advance(4000);
    // nothing new on yours after the bobs: no fidget, no walk, held at its size
    expect(anims.slice(from).filter((a) => a.seat === "0")).toHaveLength(0);
    expect(el(0, "move").style.transform).toBe("scale(1.17)");
    expect(anims.every((a) => Number.isFinite(a.iters))).toBe(true);
  });

  it("settles as you play: back to its own size, and the tag back over its head", async () => {
    await render(state());
    await render(state({ turn: 0 }));
    expect(host.querySelector<HTMLElement>(".tc-you")!.style.transform).toBe("translate(-50%, -8px)");
    await advance(2000);
    await render(state({ turn: 1, trick: { leader: 1, plays: [play(0, "HA")] } }));
    expect(anims.filter(isRelax).map((a) => a.seat)).toEqual(["0"]);
    expect(el(0, "move").style.transform).toBe("");
    expect(el(0, "walk").hasAttribute("data-ready")).toBe(false);
    expect(host.querySelector<HTMLElement>(".tc-you")!.style.transform).toBe("");
    const from = anims.length;
    await advance(3000);
    expect(anims.slice(from).filter(isBob)).toHaveLength(0);
  });

  it("is for your play and your bury as banker only: not another seat's turn, the deal, a declaration or a bury that is not yours", async () => {
    await render(state());
    await render(state({ turn: 2 }));
    await render(state({ turn: null, phase: "deal" }));
    await render(state({ turn: null, phase: "declare" }));
    await render(state({ turn: 0, phase: "bury" }));
    await render(state({ turn: 0, phase: "round_end" }));
    expect(anims.filter(isPerk)).toHaveLength(0);
    expect(el(0, "move").style.transform).toBe("");
    await render(state({ turn: 0, phase: "bury", players: [player(0, { is_banker: true }), player(1), player(2), player(3)] }));
    expect(anims.filter(isPerk)).toHaveLength(1);
  });

  it("a trick you take is hopped first; the ready jump follows it", async () => {
    await render(state());
    await render(state({ turn: 0, last_trick: taken(0, 5), trick: { leader: 0, plays: [] } }));
    expect(anims.filter(isPerk)).toHaveLength(0);
    expect(el(0, "move").getAttribute("data-move")).toBe("hop");
    await advance(520);
    expect(anims.filter(isPerk).map((a) => a.seat)).toEqual(["0"]);
  });

  it("an away player's figure sleeps through its turn", async () => {
    await render(state());
    await render(state({ turn: 0, players: [player(0, { away: true }), player(1), player(2), player(3)] }));
    expect(anims.filter(isPerk)).toHaveLength(0);
  });
});

describe("watches the play", () => {
  const card = (seat: number, n: number, over: Partial<GameState> = {}) =>
    state({ turn: 3, trick: { leader: 1, plays: Array.from({ length: n }, (_, i) => play(i === n - 1 ? seat : (seat + 3 - (n - 1 - i)) % 4, `S${i}`)) }, ...over });

  it("a card played turns each figure toward the seat that played it; that seat's own figure stays as it was", async () => {
    await render(state());
    expect(anims.filter(isLook)).toHaveLength(0);
    // the right seat (3) plays: yours, by your hand on the left, and your partner's turn and lean right
    await render(card(3, 1));
    const looks = anims.filter(isLook);
    expect(looks.map((a) => a.seat).sort()).toEqual(["0", "1", "2"]);
    expect(el(0, "face").style.transform).toMatch(/^scaleX\(1\) translateY\(0%\) rotate\([4-8]deg\) scale\(1, 1\)$/);
    expect(el(3, "face").style.transform).toBe("scaleX(-1)");
    // a turn has its small rise
    expect(text(on(0, "face")[0])).toMatch(/translateY\(-9%\)/);
  });

  it("your team's figures turn to face the card; the other team's only lean, never turning round", async () => {
    await render(state());
    const before = [0, 1, 2, 3].map((s) => /scaleX\((-?1)\)/.exec(el(s, "face").style.transform)![1]);
    // the left seat (1) plays: your partner (top) is to its right and turns left; the right seat's figure keeps its side
    await render(card(1, 1));
    const dir = (s: number) => /scaleX\((-?1)\)/.exec(el(s, "face").style.transform)![1];
    expect(dir(2)).toBe("-1");
    expect(dir(3)).toBe(before[3]);
    expect(el(3, "face").style.transform).toMatch(/rotate\(-?[4-8]deg\)/);
    expect(on(1, "face")).toHaveLength(0);
  });

  it("is not played otherwise: outside play, with no card down, or by a figure that is away", async () => {
    await render(state());
    await render(state({ phase: "bury", trick: { leader: 1, plays: [play(3, "S2")] } }));
    await render(state({ phase: "deal", trick: null }));
    await render(state({ trick: { leader: 2, plays: [] } }));
    expect(anims.filter(isLook)).toHaveLength(0);
    await render(card(3, 1, { players: [player(0), player(1), player(2, { away: true }), player(3)] }));
    expect(anims.filter(isLook).map((a) => a.seat).sort()).toEqual(["0", "1"]);
  });

  it("a figure turns at most once in 4 s, and stands straight again as the trick is collected", async () => {
    await render(state());
    await render(card(3, 1));
    expect(on(0, "face").filter(isLook)).toHaveLength(1);
    await advance(1000);
    await render(card(1, 2));
    expect(on(0, "face").filter(isLook)).toHaveLength(1);
    await advance(3100);
    await render(card(2, 3));
    // the seat across from your corner is to the right as well: the same pose is no new move
    await render(card(1, 4));
    expect(on(0, "face").filter(isLook)).toHaveLength(2);
    await render(state({ trick: { leader: 2, plays: [] }, last_trick: null }));
    expect(el(0, "face").style.transform).toMatch(/^scaleX\(-?1\)$/);
    const back = on(0, "face").at(-1)!;
    expect(back.ms).toBe(200);
  });

  it("yours does not turn while it stands ready for your turn", async () => {
    await render(state());
    await render(card(3, 1, { turn: 0 }));
    expect(on(0, "face").filter(isLook)).toHaveLength(0);
    expect(anims.filter(isPerk)).toHaveLength(1);
  });
});

describe("big plays", () => {
  it("a trick of 20 points or more: its winners jump twice, the others droop; 19 is the plain cheer and no droop", async () => {
    await render(state());
    await render(state({ last_trick: taken(0, 19) }));
    expect([0, 1, 2, 3].map((s) => el(s, "move").getAttribute("data-move"))).toEqual(["cheer", "idle", "cheer", "idle"]);
    expect(anims.filter((a) => isBig(a) || isDroop(a))).toHaveLength(0);
    await advance(9000);
    await render(state({ last_trick: taken(0, 20, 1) }));
    expect([0, 1, 2, 3].map((s) => el(s, "move").getAttribute("data-move"))).toEqual(["big", "droop", "big", "droop"]);
    expect(anims.filter(isBig).map((a) => a.seat)).toContain("0");
    expect(anims.filter(isBig).every((a) => a.ms === 1500)).toBe(true);
    expect(anims.filter(isDroop).map((a) => a.seat).sort()).toEqual(["1", "3"]);
    // the winners are drawn cheering through the jump
    expect(host.querySelector('.tc-seat[data-seat="0"] svg')!.getAttribute("data-pose")).toBe("cheer");
    await advance(1800);
    expect([0, 1, 2, 3].map((s) => el(s, "move").getAttribute("data-move"))).toEqual(["idle", "idle", "idle", "idle"]);
  });

  it("two tricks alike, 9 s apart, are each a big play: the server's count of tricks tells them apart", async () => {
    await render(state({ tricks_done: 0 }));
    await render(state({ tricks_done: 1, last_trick: taken(0, 25) }));
    expect(anims.filter(isDroop).map((a) => a.seat).sort()).toEqual(["1", "3"]);
    await advance(9000);
    expect([0, 1, 2, 3].map((s) => el(s, "move").getAttribute("data-move"))).toEqual(["idle", "idle", "idle", "idle"]);
    await render(state({ tricks_done: 2, last_trick: taken(0, 25) }));
    expect([0, 1, 2, 3].map((s) => el(s, "move").getAttribute("data-move"))).toEqual(["big", "droop", "big", "droop"]);
    expect(anims.filter(isDroop).map((a) => a.seat).sort()).toEqual(["1", "1", "3", "3"]);
    // a third alike 4 s on is inside the big plays' gap: the plain cheer, as any trick there
    await advance(4000);
    await render(state({ tricks_done: 3, last_trick: taken(0, 25) }));
    expect([0, 1, 2, 3].map((s) => el(s, "move").getAttribute("data-move"))).toEqual(["cheer", "idle", "cheer", "idle"]);
  });

  it("two small tricks alike are each hopped; the same trick on a later frame is not hopped again", async () => {
    await render(state({ tricks_done: 0 }));
    await render(state({ tricks_done: 1, last_trick: taken(0, 5) }));
    await advance(2000);
    const hops = () => on(0, "move").filter((a) => a.ms === 500).length;
    expect(hops()).toBe(1);
    await render(state({ tricks_done: 1, turn: 2, last_trick: taken(0, 5) }));
    expect(hops()).toBe(1);
    await render(state({ tricks_done: 2, last_trick: taken(0, 5) }));
    expect(hops()).toBe(2);
  });

  it("from a server that sends no count a different trick is still taken, and the same one not again", async () => {
    await render(state());
    await render(state({ last_trick: taken(0, 25) }));
    await advance(9000);
    await render(state({ turn: 2, last_trick: taken(0, 25) }));
    expect(anims.filter(isBig).filter((a) => a.seat === "0")).toHaveLength(1);
    await render(state({ last_trick: taken(0, 25, 1) }));
    expect(anims.filter(isBig).filter((a) => a.seat === "0")).toHaveLength(2);
  });

  it("the other side taking 20 or more droops yours", async () => {
    await render(state());
    await render(state({ last_trick: taken(1, 25) }));
    expect([0, 1, 2, 3].map((s) => el(s, "move").getAttribute("data-move"))).toEqual(["droop", "big", "droop", "big"]);
    expect(anims.filter(isDroop).map((a) => a.seat).sort()).toEqual(["0", "2"]);
  });

  it("big plays are at least 8 s apart: one sooner is the plain cheer, with no droop", async () => {
    await render(state());
    await render(state({ last_trick: taken(0, 20) }));
    await advance(4000);
    await render(state({ last_trick: taken(1, 30, 1) }));
    expect([0, 1, 2, 3].map((s) => el(s, "move").getAttribute("data-move"))).toEqual(["idle", "cheer", "idle", "cheer"]);
    expect(anims.filter(isDroop).map((a) => a.seat).sort()).toEqual(["1", "3"]);
    await advance(4100);
    await render(state({ last_trick: taken(1, 30, 2) }));
    expect([0, 1, 2, 3].map((s) => el(s, "move").getAttribute("data-move"))).toEqual(["droop", "big", "droop", "big"]);
  });

  it("a tractor led is its team's two quick hops; a pair led, or a tractor played to follow, is not", async () => {
    await render(state());
    await render(state({ trick: { leader: 2, plays: [play(2, "S3", "pair")] } }));
    await render(state({ trick: { leader: 2, plays: [play(2, "S3", "pair"), play(3, "S4", "tractor")] } }));
    expect(anims.filter(isChug)).toHaveLength(0);
    await render(state({ trick: { leader: 0, plays: [play(0, "S5", "tractor")] } }));
    expect(anims.filter(isChug).map((a) => a.seat).sort()).toEqual(["0", "2"]);
    expect([0, 1, 2, 3].map((s) => el(s, "move").getAttribute("data-move"))).toEqual(["chug", "idle", "chug", "idle"]);
    // the same lead on a later frame is not led again
    await advance(9000);
    await render(state({ trick: { leader: 0, plays: [play(0, "S5", "tractor"), play(1, "S9")] } }));
    expect(anims.filter(isChug)).toHaveLength(2);
  });

  it("a tractor within 8 s of a big trick is not marked", async () => {
    await render(state());
    await render(state({ last_trick: taken(0, 20) }));
    await advance(3000);
    await render(state({ last_trick: taken(0, 20), trick: { leader: 0, plays: [play(0, "S5", "tractor")] } }));
    expect(anims.filter(isChug)).toHaveLength(0);
  });

  it("a kitty taken on the last trick: the takers' special once the sheet has closed, and a droop for the team that lost the round with it", async () => {
    await render(state());
    // seat 1 is the banker, so your team attacks; you take the last trick with points buried
    const end = { winner_team: 0, level_change: 0, new_levels: ["2", "2"], kitty_points: 20, kitty_cards: [] };
    await render(state({ phase: "round_end", last_trick: taken(0, 5), round_result: end } as unknown as Partial<GameState>));
    await advance(3000);
    expect(anims.filter(isDroop)).toHaveLength(0);
    expect([0, 1, 2, 3].map((s) => el(s, "move").getAttribute("data-move")).includes("react")).toBe(false);
    await render(state({ phase: "deal", turn: null, last_trick: taken(0, 5) }));
    expect([0, 1, 2, 3].map((s) => el(s, "move").getAttribute("data-move"))).toEqual(["react", "droop", "react", "droop"]);
    expect(anims.filter(isDroop).map((a) => a.seat).sort()).toEqual(["1", "3"]);
  });

  it("no kitty taken, no droop: the defenders took the last trick, or nothing was buried", async () => {
    await render(state());
    const end = { winner_team: 0, level_change: 0, new_levels: ["2", "2"], kitty_points: 0, kitty_cards: [] };
    await render(state({ phase: "round_end", last_trick: taken(0, 5), round_result: end } as unknown as Partial<GameState>));
    await render(state({ phase: "deal", turn: null, last_trick: taken(0, 5) }));
    expect([0, 1, 2, 3].map((s) => el(s, "move").getAttribute("data-move"))).toEqual(["react", "idle", "react", "idle"]);
    expect(anims.filter(isDroop)).toHaveLength(0);
  });

  it("the other side taking the kitty but losing the round plays its special; yours plays its own for the round, and nobody droops", async () => {
    await render(state({ banker: 0 }));
    const end = { winner_team: 0, level_change: 0, new_levels: ["2", "2"], kitty_points: 40, kitty_cards: [] };
    await render(state({ banker: 0, phase: "round_end", last_trick: taken(1, 5), round_result: end } as unknown as Partial<GameState>));
    await render(state({ banker: 0, phase: "deal", turn: null, last_trick: taken(1, 5) }));
    expect([0, 1, 2, 3].map((s) => el(s, "move").getAttribute("data-move"))).toEqual(["react", "react", "react", "react"]);
    expect(anims.filter(isDroop)).toHaveLength(0);
  });

  it("nothing big starts behind the round-end sheet", async () => {
    await render(state());
    const end = { winner_team: 1, level_change: 0, new_levels: ["2", "2"], kitty_points: 0, kitty_cards: [] };
    await render(state({ phase: "round_end", last_trick: taken(1, 30), round_result: end } as unknown as Partial<GameState>));
    expect(anims.filter((a) => isBig(a) || isDroop(a))).toHaveLength(0);
  });
});

describe("under Reduce Motion each is a held pose, and nothing animates", () => {
  beforeEach(() => { reduced = true; });

  it("ready is the larger size alone, for as long as the turn lasts", async () => {
    await render(state());
    await render(state({ turn: 0 }));
    await advance(6000);
    expect(el(0, "move").style.transform).toBe("scale(1.17)");
    await render(state({ turn: 1 }));
    expect(el(0, "move").style.transform).toBe("");
    expect(anims).toHaveLength(0);
  });

  it("watching is the turn itself, held", async () => {
    await render(state());
    await render(state({ trick: { leader: 3, plays: [play(3, "S2")] } }));
    expect(el(0, "face").style.transform).toMatch(/rotate\([4-8]deg\)/);
    await render(state({ trick: { leader: 3, plays: [] } }));
    expect(el(0, "face").style.transform).toBe("scaleX(1)");
    expect(anims).toHaveLength(0);
  });

  it("a big play is the cheer drawn still for the winners and the droop held for a second for the others", async () => {
    await render(state());
    await render(state({ last_trick: taken(0, 20) }));
    expect(host.querySelector('.tc-seat[data-seat="0"] svg')!.classList.contains("cmp-still")).toBe(true);
    expect(host.querySelector('.tc-seat[data-seat="0"] svg')!.getAttribute("data-pose")).toBe("cheer");
    expect(el(1, "move").style.transform).toMatch(/^rotate\([246]deg\) scale\(1\.07, 0\.84\)$/);
    await advance(1100);
    expect(el(1, "move").style.transform).toBe("");
    expect(el(1, "move").getAttribute("data-move")).toBe("idle");
    expect(anims).toHaveLength(0);
  });

  it("a tractor led moves nothing", async () => {
    await render(state());
    await render(state({ trick: { leader: 0, plays: [play(0, "S5", "tractor")] } }));
    await advance(1000);
    expect(anims).toHaveLength(0);
    expect(el(0, "move").style.transform).toBe("");
  });
});

describe("how much a figure does", () => {
  // the clock moves a tenth of a second at a time, so a move that ends is followed at once, as on a real table
  const pass = async (ms: number) => { for (let t = 0; t < ms; t += 100) await advance(100); };
  /** A round: a card every `cardMs`, the trick collected 1 s after its
   *  fourth, the winner leading the next; the teams take tricks in turn.
   *  Returns each visible move of `seat` as `time:kind`. A ready turn that
   *  only grows (no jump) is not counted as one. */
  const round = async (tricks: number, seat: number, cardMs: number) => {
    await render(state({ turn: 1 }));
    let leader = 1;
    let last: GameState["last_trick"] = null;
    for (let t = 0; t < tricks; t++) {
      const plays: TrickPlay[] = [];
      for (let i = 0; i < 4; i++) {
        const who = (leader + i) % 4;
        await render(state({ turn: who, trick: { leader, plays: [...plays] }, last_trick: last }));
        await pass(cardMs);
        plays.push(play(who, `C${t}-${i}`));
      }
      await render(state({ turn: null, trick: { leader, plays: [...plays] }, last_trick: last }));
      await pass(1000);
      // every eighth trick is a big one, every third worth 10
      const winner = t % 4;
      last = { leader, winner, points: t % 8 === 5 ? 25 : t % 3 === 1 ? 10 : 0, plays };
      leader = winner;
    }
    const jump = (a: Rec) => isPerk(a) && a.ms === 520;
    const visible = (a: Rec) => a.seat === String(seat) && !a.cancelled
      && (jump(a) || isBig(a) || isDroop(a) || isChug(a) || isLook(a)
        || (a.box === "tc-move" && (a.ms === 500 || a.ms === 1200)) || (a.box === "tc-walk" && a.ms > 500));
    return anims.filter(visible).map((a) => `${a.at}:${jump(a) ? "ready" : isLook(a) ? "watch" : a.box === "tc-walk" ? "walk" : isBig(a) || isDroop(a) ? "big" : "trick"}`);
  };
  const perMinute = (moves: string[], from: number, to: number, kind = "") => {
    const at = moves.filter((x) => !kind || x.endsWith(`:${kind}`)).map((x) => Number(x.split(":")[0]));
    const out: number[] = [];
    for (let t = from; t + 60000 <= to; t += 60000) out.push(at.filter((x) => x >= t && x < t + 60000).length);
    return out;
  };
  const mean = (list: number[]) => list.reduce((a, b) => a + b, 0) / list.length;
  const kinds = (moves: string[]) => { const n: Record<string, number> = {}; for (const x of moves) n[x.split(":")[1]] = (n[x.split(":")[1]] ?? 0) + 1; return JSON.stringify(n); };

  it("through a round at a person's pace (a card every 3.5 s, 25 tricks in 6 min) yours makes 6 to 8 visible moves a minute, never more than 12 in one", async () => {
    const t0 = Date.now();
    const at = await round(25, 0, 3500);
    const mins = perMinute(at, t0, Date.now());
    expect(mins.length).toBeGreaterThanOrEqual(6);
    expect(mean(mins), mins.join(",") + kinds(at)).toBeGreaterThanOrEqual(6);
    expect(mean(mins), mins.join(",") + kinds(at)).toBeLessThanOrEqual(8);
    expect(Math.max(...mins), mins.join(",")).toBeLessThanOrEqual(12);
    // it is the game's moves that fill the minute: ready each turn, and it watches
    // (a turn back within 8 s of the last jump, leading after taking the trick, only grows)
    expect(at.filter((x) => x.endsWith(":ready")).length).toBeGreaterThanOrEqual(20);
    expect(at.filter((x) => x.endsWith(":watch")).length).toBeGreaterThan(0);
  });

  it("another figure makes fewer at that pace: 2 to 5 a minute, never more than 8", async () => {
    const t0 = Date.now();
    const at = await round(25, 3, 3500);
    const mins = perMinute(at, t0, Date.now());
    expect(mean(mins), mins.join(",") + kinds(at)).toBeGreaterThanOrEqual(2);
    expect(mean(mins), mins.join(",") + kinds(at)).toBeLessThanOrEqual(5);
    expect(Math.max(...mins), mins.join(",")).toBeLessThanOrEqual(8);
  });

  it("at a brisk table (a card every 1.5 s) yours stays at 12 a minute or under", async () => {
    const t0 = Date.now();
    const at = await round(30, 0, 1500);
    const mins = perMinute(at, t0, Date.now());
    expect(Math.max(...mins), mins.join(",") + kinds(at)).toBeLessThanOrEqual(12);
  });

  it("at a table of bots (a card every 0.3 s) the ready jump is at most 8 a minute, a watch 8 and a big play 8, whatever the tricks do", async () => {
    const t0 = Date.now();
    const at = await round(80, 0, 300);
    for (const [kind, most] of [["ready", 8], ["watch", 8], ["big", 8]] as const) {
      const mins = perMinute(at, t0, Date.now(), kind);
      expect(Math.max(...mins), `${kind} ${mins.join(",")}`).toBeLessThanOrEqual(most);
    }
    // the turn still shows every time: the size without the jump
    expect(anims.filter((a) => a.seat === "0" && isPerk(a) && a.ms === 200).length).toBeGreaterThan(20);
  });
});

// Every companion's character at the table, and a store character's
// material on top of it (`flair.ts`): which seats bring pieces, when, on
// which layer, and that nothing starts in the deal or under Reduce Motion.
describe("character and material at the table", () => {
  let spawn: ReturnType<typeof vi.spyOn>;
  let rest: ReturnType<typeof vi.spyOn>;
  let sized: ReturnType<typeof vi.spyOn>;
  let ctx: unknown;
  const realCtx = HTMLCanvasElement.prototype.getContext;
  beforeEach(() => {
    spawn = vi.spyOn(FlairLayer.prototype, "spawn");
    rest = vi.spyOn(FlairLayer.prototype, "rest");
    sized = vi.spyOn(FlairLayer.prototype, "resize");
    HTMLCanvasElement.prototype.getContext = (() => null) as unknown as typeof realCtx;
    ctx = null;
  });
  afterEach(() => { spawn.mockRestore(); rest.mockRestore(); sized.mockRestore(); HTMLCanvasElement.prototype.getContext = realCtx; void ctx; });
  /** Yours a Lamb, the left seat a Panda, the other two free. */
  const paid = (over: Partial<GameState> = {}) => state({ players: [player(0, { look: "lamb/newyear" }), player(1, { look: "panda/classic" }), player(2), player(3)], ...over });
  const calls = (tag: string, owner?: string) => (spawn.mock.calls as unknown as [string, boolean, string, Piece[]][])
    .map((c, i) => ({ owner: c[0], own: c[1], tag: c[2], pieces: c[3], started: spawn.mock.results[i]?.value as number }))
    .filter((c) => c.tag === tag && (owner === undefined || c.owner === owner));
  /** The felt's layer, from its first sizing to the felt. */
  const layer = () => sized.mock.instances[0] as unknown as FlairLayer;
  const click = (x: number, y: number) => act(() => { host.querySelector(".felt")!.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: x, clientY: y })); });

  it("a table of free companions draws no canvas; a store character brings one under the figures and one over them", async () => {
    await render(state());
    expect(host.querySelectorAll("canvas")).toHaveLength(0);
    await render(paid());
    const kids = [...host.querySelector(".table-companions")!.children];
    expect(kids[0].matches('canvas.tc-flair[data-depth="back"]')).toBe(true);
    expect(kids[kids.length - 1].matches('canvas.tc-flair[data-depth="front"]')).toBe(true);
    // the trail's layer comes before every figure, so it is drawn under them
    const seats = kids.filter((k) => k.matches(".tc-seat"));
    expect(seats).toHaveLength(4);
    for (const s of seats) expect(kids.indexOf(s)).toBeGreaterThan(0);
    for (const s of seats) expect(kids.indexOf(s)).toBeLessThan(kids.length - 1);
  });

  it("the watch screen draws the figures with no pieces", async () => {
    await act(async () => { root.render(<div className="felt"><div className="opponent pos-left" /><div className="opponent pos-top" /><div className="opponent pos-right" />
      <div className="you-row" /><div className="hand"><div className="hand-slot" /></div><TableCompanions state={paid()} watch={{ quiet: false }} /></div>); });
    expect(host.querySelectorAll(".tc-seat").length).toBeGreaterThan(0);
    expect(host.querySelectorAll("canvas")).toHaveLength(0);
    await advance(20000);
    expect(spawn).not.toHaveBeenCalled();
  });

  /** The table before its other three people sit down: bots, who have no companion. */
  const alone = (over: Partial<GameState> = {}) => state({ players: [player(0, { look: "lamb/newyear" }),
    ...[1, 2, 3].map((s) => player(s, { is_bot: true, look: null }))], ...over });
  const arrive = (seat: number) => anims.filter((a) => a.seat === String(seat) && a.box === "tc-move" && isArrive(a));

  it("a table opened or reconnected into draws everyone settled: no way in, no entrance", async () => {
    await render(paid());
    await advance(3000);
    expect(anims.filter(isArrive)).toHaveLength(0);
    expect(calls("entrance")).toHaveLength(0);
  });

  it("a person who sits down at a table already shown: their companion comes in its own way, a store character with its entrance at another seat's share", async () => {
    await render(alone());
    await advance(1000);
    await render(paid());
    expect(arrive(0)).toHaveLength(0);
    for (const seat of [1, 2, 3]) expect(arrive(seat), `seat ${seat}`).toHaveLength(1);
    expect(new Set([1, 2, 3].map((s) => text(arrive(s)[0]))).size).toBe(3);
    expect(calls("entrance").map((c) => [c.owner, c.own])).toEqual([["1", false]]);
    expect(calls("entrance", "1")[0].pieces.length).toBeLessThanOrEqual(4);
    // once: a later frame plays none
    await render(paid({ turn: 2 }));
    expect([1, 2, 3].flatMap(arrive)).toHaveLength(3);
  });

  it("a figure first drawn while the hand is dealt is simply there: no move and no pieces, then or later", async () => {
    await render(alone());
    await advance(1000);
    await render(paid({ phase: "deal" } as Partial<GameState>));
    expect(anims.filter(isArrive)).toHaveLength(0);
    expect(calls("entrance")).toHaveLength(0);
    await render(paid());
    await advance(3000);
    expect(anims.filter(isArrive)).toHaveLength(0);
    expect(calls("entrance")).toHaveLength(0);
  });

  it("nothing starts while the hand is dealt, and what was in the air as the deal begins is taken off", async () => {
    await render(paid());
    const clear = vi.spyOn(FlairLayer.prototype, "clear");
    expect(layer().dealing).toBe(false);
    await render(paid({ phase: "deal" } as Partial<GameState>));
    expect(layer().dealing).toBe(true);
    expect(clear).toHaveBeenCalled();
    expect(layer().spawn("0", true, "burst", [])).toBe(0);
    await render(paid());
    expect(layer().dealing).toBe(false);
    clear.mockRestore();
  });

  it("yours walks in its own gait at the walk's pace, and a store character drops its trail behind it as each hop lands, under the figures", async () => {
    await render(paid());
    await advance(1500);
    const from = anims.length;
    click(m.felt.w / 2, m.felt.h * 0.42);
    const walk = on(0, "walk", from)[0], gait = on(0, "face", from)[0];
    expect(walk).toBeTruthy();
    // the Lamb's prance, a whole number of 520 ms steps fitted to the walk
    expect(text(gait)).toContain("translateY(-12%) rotate(4deg)");
    expect(gait.ms * gait.iters).toBeCloseTo(walk.ms, 5);
    expect(Math.abs(gait.ms - 520)).toBeLessThan(260);
    const before = calls("trail").length;
    await advance(walk.ms + 50);
    const trail = calls("trail").slice(before);
    expect(trail).toHaveLength(Math.max(1, Math.round(walk.ms / 520)));
    for (const c of trail) {
      expect([c.owner, c.own]).toEqual(["0", true]);
      expect(c.pieces.length).toBeGreaterThanOrEqual(2);
      expect(c.pieces.length).toBeLessThanOrEqual(3);
      for (const p of c.pieces) expect(p.depth).toBe("back");
    }
    // behind it: it walked to the right or the left, and every piece lands on the side it came from
    const xs = walk.frames.map((k) => Number(/translate\(([-\d.]+)px/.exec(String(k.transform))![1]));
    const dir = Math.sign(xs[xs.length - 1] - xs[0]) || 1;
    const last = trail[trail.length - 1];
    for (const p of last.pieces) expect((p.keys[p.keys.length - 1].x - (xs[xs.length - 1] + 22)) * dir).toBeLessThan(0);
  });

  it("a free companion walks in its own gait too, and drops nothing", async () => {
    await render(state());
    await advance(1500);
    const from = anims.length;
    click(m.felt.w / 2, m.felt.h * 0.42);
    expect(text(on(0, "face", from)[0])).toContain("scale(1.08, 0.9)");
    await advance(4000);
    expect(spawn).not.toHaveBeenCalled();
  });

  it("a habit of its own is one of its fidgets at rest: after the sway, the blink and the small hop", async () => {
    await render(state({ players: [player(0), player(1, { look: "tractor/red" }), player(2), player(3)] }));
    await advance(1000);
    const from = anims.length;
    const seen: Rec[] = [];
    for (let t = 0; t < 60000 && seen.length < 3; t += 100) { await advance(100); seen.splice(0, seen.length, ...on(1, "move", from)); }
    expect(seen.map((a) => a.ms)).toEqual([600, 420, 700]);
    expect(text(seen[2])).toContain("rotate(-1.5deg)");
  });

  it("a big play: the store character that won it bursts in its own pieces and mark; the one that lost it lets one piece fall", async () => {
    await render(paid());
    await advance(9000);
    const from = spawn.mock.calls.length;
    await render(paid({ last_trick: taken(0, 25, 1) }));
    const burst = calls("burst").slice(calls("burst").length - (spawn.mock.calls.length - from));
    const mine = burst.find((c) => c.owner === "0")!, theirs = burst.find((c) => c.owner === "1")!;
    expect(mine.own).toBe(true);
    expect(mine.pieces.filter((p) => p.shape === "petal")).toHaveLength(7);
    expect(mine.pieces.filter((p) => p.shape === "blossom")).toHaveLength(1);
    expect(mine.pieces.length).toBeLessThanOrEqual(11);
    expect(theirs.own).toBe(false);
    expect(theirs.pieces).toHaveLength(1);
    expect(theirs.pieces[0].shape).toBe("leaf");
  });

  it("a round won: the store character's shower comes with its special once the sheet has closed, never behind it", async () => {
    await render(paid());
    const end = { winner_team: 0, level_change: 0, new_levels: ["2", "2"], kitty_points: 0 };
    await render(paid({ phase: "round_end", round_result: end } as unknown as Partial<GameState>));
    await advance(3000);
    expect(calls("shower")).toHaveLength(0);
    await render(paid());
    const shower = calls("shower");
    expect(shower.map((c) => c.owner)).toEqual(["0"]);
    expect(shower[0].pieces.filter((p) => p.shape === "petal")).toHaveLength(6);
    expect(shower[0].pieces.length).toBeLessThanOrEqual(9);
    expect(el(0, "move").getAttribute("data-move")).toBe("react");
  });

  it("a tap on your Lamb plays the horn butt for 1.5 s: the table lunges it as far as stays clear, and its accent fans out ahead of it", async () => {
    await render(paid());
    await advance(1500);
    const from = anims.length, before = calls("burst").length;
    act(() => { el(0, "walk").dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    expect(el(0, "move").getAttribute("data-move")).toBe("react");
    const accent = calls("burst").slice(before);
    expect(accent).toHaveLength(1);
    expect(accent[0].pieces).toHaveLength(3);
    expect(accent[0].pieces[0].delay).toBe(690);
    const lunge = on(0, "walk", from);
    for (const a of lunge) {
      expect(a.ms).toBe(1500);
      expect(a.frames[0].transform).toBe(a.frames[a.frames.length - 1].transform);
    }
    await advance(1450);
    expect(el(0, "move").getAttribute("data-move")).toBe("react");
    await advance(100);
    expect(el(0, "move").getAttribute("data-move")).toBe("idle");
  });

  it("another seat's shared special plays here with its accent, at the other seats' share", async () => {
    const shared = (n: number) => (
      <div className="felt"><div className="opponent pos-left" /><div className="opponent pos-top" /><div className="opponent pos-right" />
        <div className="you-row" /><div className="hand"><div className="hand-slot" /></div>
        <TableCompanions state={paid()} shared={n ? { 1: { act: "special", n } } : {}} /></div>);
    await act(async () => { root.render(shared(0)); });
    await advance(1500);
    const before = calls("burst").length;
    await act(async () => { root.render(shared(1)); });
    expect(el(1, "move").getAttribute("data-move")).toBe("react");
    const accent = calls("burst").slice(before);
    // the Panda's two bites, one fleck each
    expect(accent.map((c) => [c.owner, c.own, c.pieces.length, c.pieces[0].delay])).toEqual([["1", false, 1, 780], ["1", false, 1, 1200]]);
  });

  it("a store character's cue shows on its own clock at rest", async () => {
    await render(paid());
    await advance(1500);
    expect(calls("cue")).toHaveLength(0);
    await advance(8000);
    expect(calls("cue").map((c) => c.owner).sort()).toEqual(["0", "1"]);
    expect(calls("cue", "0")[0].pieces.map((p) => p.shape)).toEqual(["spark", "spark"]);
    expect(calls("cue", "1")[0].pieces.map((p) => p.shape)).toEqual(["ripple", "ripple"]);
  });

  it("from level 6 your team's store character's pieces turn part gold", async () => {
    await render(paid({ levels: ["6", "2"] }));
    await advance(1500);
    click(m.felt.w / 2, m.felt.h * 0.42);
    await advance(3500);
    const tints = calls("trail").flatMap((c) => c.pieces.map((p) => p.c1));
    expect(tints.length).toBeGreaterThan(2);
    expect(tints).toContain("#fff3c0");
  });

  it("under Reduce Motion nothing moves or starts: a store character has three still pieces at its feet", async () => {
    reduced = true;
    await render(paid());
    await advance(20000);
    expect(anims).toHaveLength(0);
    expect(spawn.mock.results.every((r: { value?: unknown }) => r.value === 0)).toBe(true);
    const still = (rest.mock.calls as unknown as [string, Piece[] | null][]).filter((c) => c[1]);
    expect(still.map((c) => c[0]).sort()).toEqual(["0", "1"]);
    for (const c of still) expect(c[1]).toHaveLength(3);
  });
});
