// Two companion moves are shared with the table: a tap on yours plays its
// special for everyone, and a tap on the felt parks it there for everyone,
// as a point of the felt's safe area from 0 to 1. Another seat's shared move
// plays on its own figure, a parked spot carried in the frame places it on a
// rejoin, a viewer not shown companions takes none, and Reduce Motion gets
// the still pose and the final spot. The table is drawn with the phone's
// measured rects and a recorded `Element.animate` on a fake clock.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthState } from "../auth";
import type { CompanionShare, GameState, StatePlayer } from "../protocol";

const { authState } = vi.hoisted(() => ({
  authState: { current: { status: "out", clientId: "cid", user: null } as AuthState },
}));
vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));
vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return { ...real, useAuth: () => authState.current, auth: { updated: () => {}, get state() { return authState.current; } } };
});

import TableCompanions from "./TableCompanions";
import type { SharedMoves } from "./TableCompanions";
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

let sent: CompanionShare[] = [];
const table = (s: GameState, shared: SharedMoves = {}) => (
  <div className="felt">
    <div className="opponent pos-left" /><div className="opponent pos-top" /><div className="opponent pos-right" />
    <div className="you-row" /><div className="hand"><div className="hand-slot" /></div>
    <TableCompanions state={s} shared={shared} onShare={(m) => sent.push(m)} />
  </div>
);
const render = async (s: GameState, shared: SharedMoves = {}) => { await act(async () => { root.render(table(s, shared)); }); };
const advance = async (ms: number) => {
  await act(async () => { vi.advanceTimersByTime(ms); for (let i = 0; i < 6; i++) await Promise.resolve(); });
  await act(async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); });
};
const el = (seat: number, part: "walk" | "face" | "move") => host.querySelector<HTMLElement>(`.tc-seat[data-seat="${seat}"] .tc-${part}`)!;
const on = (seat: number, part: "walk" | "face" | "move", from = 0) => anims.slice(from).filter((a) => a.seat === String(seat) && a.box === `tc-${part}`);
const pose = (seat: number) => host.querySelector(`.tc-seat[data-seat="${seat}"] svg.cmp`)?.getAttribute("data-pose");
const at = (seat: number) => el(seat, "walk").style.transform;
const walks = (seat: number, from = 0) => on(seat, "walk", from).filter((a) => a.ms >= 1000);
const felt = () => host.querySelector<HTMLElement>(".felt")!;
const tapFelt = async (x: number, y: number) => {
  await act(async () => { felt().dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: x, clientY: y })); });
};

beforeEach(() => { sent = []; });

describe("yours is shared", () => {
  it("a tap on yours plays its special and tells the table; a tap on the felt parks it and tells the table where", async () => {
    await render(state());
    await advance(500);
    await act(async () => { el(0, "walk").click(); });
    expect(pose(0)).toBe("react");
    expect(sent).toEqual([{ type: "companion", act: "special" }]);
    await advance(4000);
    await tapFelt(m.felt.w * 0.5, m.felt.h * 0.45);
    const home = sent.find((s) => s.act === "home");
    expect(home).toBeDefined();
    if (home?.act === "home") {
      expect(home.x).toBeGreaterThan(0.2); expect(home.x).toBeLessThan(0.8);
      expect(home.y).toBeGreaterThan(0.2); expect(home.y).toBeLessThan(0.8);
    }
  });
});

describe("another seat's shared moves", () => {
  it("a special plays on that seat's figure only", async () => {
    await render(state());
    await advance(500);
    await render(state(), { 2: { act: "special", n: 1 } });
    expect(pose(2)).toBe("react");
    for (const seat of [0, 1, 3]) expect(pose(seat)).not.toBe("react");
    // the same move seen again plays nothing more; a new one plays again
    await advance(4000);
    await render(state(), { 2: { act: "special", n: 1 } });
    expect(pose(2)).not.toBe("react");
    await render(state(), { 2: { act: "special", n: 2 } });
    expect(pose(2)).toBe("react");
    expect(sent).toEqual([]);
  });

  it("a parked spot walks that seat's figure there, and it stays", async () => {
    await render(state());
    await advance(500);
    const from = anims.length;
    const before = at(1);
    await render(state(), { 1: { act: "home", x: 0.5, y: 0.45, n: 1 } });
    expect(walks(1, from).length).toBe(1);
    expect(walks(0, from)).toHaveLength(0);
    expect(walks(3, from)).toHaveLength(0);
    await advance(5000);
    expect(at(1)).not.toBe(before);
  });

  it("a parked spot the frame carries places that seat's figure on a rejoin, with no walk", async () => {
    await render(state());
    await advance(500);
    const by = at(1);
    act(() => root.unmount());
    root = createRoot(host);
    anims = [];
    await render(state({ players: [player(0), player(1, { home: [0.5, 0.45] }), player(2), player(3)] }));
    await advance(500);
    expect(at(1)).not.toBe(by);
    expect(walks(1)).toHaveLength(0);
  });

  it("under Reduce Motion a special is the still pose and a parked spot is reached at once", async () => {
    reduced = true;
    await render(state());
    await advance(500);
    const from = anims.length;
    const before = at(1);
    await render(state(), { 3: { act: "special", n: 1 }, 1: { act: "home", x: 0.5, y: 0.45, n: 2 } });
    expect(pose(3)).toBe("react");
    expect(host.querySelector('.tc-seat[data-seat="3"] svg.cmp')!.classList.contains("cmp-still")).toBe(true);
    expect(walks(1, from)).toHaveLength(0);
    expect(at(1)).not.toBe(before);
  });

  it("a viewer not shown companions at the table draws none and takes none", async () => {
    window.localStorage.setItem("shengji.companions", "off");
    await render(state());
    await render(state(), { 1: { act: "special", n: 1 }, 2: { act: "home", x: 0.5, y: 0.5, n: 2 } });
    expect(host.querySelector(".tc-seat")).toBeNull();
    expect(anims).toHaveLength(0);
  });
});
