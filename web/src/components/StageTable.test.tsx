// The Collection stage's Stage · Table switch: the switch is labels only and
// kept on this device; the Table view mounts the table's own companion layer
// on a fixture seat, so yours stands at the size the table gives the bottom
// seat on the same screen, with no hand, no nameplate and nobody else's; the
// chips play the table's own moves there, and a tap on the felt walks it.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthState } from "../auth";
import type { GameState, StatePlayer } from "../protocol";

const { authState } = vi.hoisted(() => ({
  authState: { current: { status: "out", clientId: "cid", user: null } as AuthState },
}));
vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));
vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return { ...real, useAuth: () => authState.current, auth: { updated: () => {}, get state() { return authState.current; } } };
});

import { Stage } from "./CharacterPage";
import TableCompanions from "../companion/TableCompanions";
import { TABLES } from "../companion/seatZones.fixtures";
import type { Rect } from "../companion/seatZones";
import { TABLET_SCREEN } from "../phoneLayout";
import { setLanguageChoice } from "../i18n";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const m = TABLES["phone-land-w2"];
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let spy: ReturnType<typeof vi.spyOn>;
let anims: { box: string; frames: Keyframe[] }[];
let had: unknown;
let tablet = false;
const realMatch = window.matchMedia;
const proto = Element.prototype as unknown as { animate?: unknown };

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  try { window.localStorage.clear(); } catch { /* none */ }
  authState.current = { status: "out", clientId: "cid", user: null, collection: true } as AuthState;
  // the real table's felt (a phone's, measured) and the Table view's seat felt
  const rects: Record<string, Rect> = {
    felt: { x: 0, y: 0, ...m.felt }, "pos-left": m.plates.left!, "pos-top": m.plates.top!, "pos-right": m.plates.right!,
    "you-row": m.row!, hand: m.hand, "hand-slot": m.firstCard,
    "char-seat": { x: 0, y: 0, w: 326, h: 180 },
  };
  const viewRects: Record<string, Rect> = { hand: { x: 8, y: 179, w: 310, h: 1 }, "hand-slot": { x: 8, y: 179, w: 1, h: 1 } };
  spy = vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const inView = this.closest(".char-seat") !== null;
    const k = Object.keys(rects).find((c) => this.classList.contains(c));
    const r = k ? (inView && viewRects[k] ? viewRects[k] : rects[k]) : { x: 0, y: 0, w: 0, h: 0 };
    return { left: r.x, top: r.y, width: r.w, height: r.h, right: r.x + r.w, bottom: r.y + r.h, x: r.x, y: r.y, toJSON: () => ({}) } as DOMRect;
  });
  vi.useFakeTimers();
  anims = [];
  had = proto.animate;
  proto.animate = function (this: Element, frames: Keyframe[], opts: KeyframeAnimationOptions) {
    let timer = 0;
    const finished = new Promise<void>((r) => { timer = window.setTimeout(r, Number(opts?.duration ?? 0)); });
    anims.push({ box: this.className.toString().split(" ")[0], frames });
    return { finished, cancel: () => window.clearTimeout(timer) };
  };
  tablet = false;
  window.matchMedia = ((q: string) => ({ matches: q === TABLET_SCREEN ? tablet : false, media: q,
    addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
  setLanguageChoice("en");
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  proto.animate = had;
  window.matchMedia = realMatch;
  spy.mockRestore();
  vi.useRealTimers();
  setLanguageChoice("system");
});

const flush = async (ms = 50) => {
  await act(async () => { vi.advanceTimersByTime(ms); for (let i = 0; i < 6; i++) await Promise.resolve(); });
};
const stage = async (arrives = 0) => {
  await act(async () => { root.render(<Stage kind="bun" colour="plain" size={176} label="Bun · Plain" moves arrives={arrives} />); });
  await flush();
};
const option = (name: string) => [...host.querySelectorAll<HTMLButtonElement>(".char-view .segmented-btn")].find((b) => b.textContent === name)!;
const chip = (name: string) => [...host.querySelectorAll<HTMLButtonElement>(".char-poses .char-move")].find((b) => b.textContent === name)!;
const toTable = async () => { await act(async () => { option("Table").click(); }); await flush(); };

/** The size the real table draws the bottom seat (you) at on this screen. */
async function tableSeatSize(): Promise<number> {
  const player = (seat: number): StatePlayer => ({ seat, name: `P${seat}`, is_bot: seat !== 0, look: seat === 0 ? "bun/plain" : null, connected: true,
    team: (seat % 2) as 0 | 1, cards_left: 25, is_banker: false, takeover_in: null, controller: seat === 0 ? "human" : "bot", reserved_for: null, reserved_secs: null });
  const state = { you: 0, room: "R", phase: "play", levels: ["2", "2"], players: [0, 1, 2, 3].map(player), turn: 1, banker: 1,
    trick: { leader: 1, plays: [] }, last_trick: null, round_result: null } as unknown as GameState;
  await act(async () => { root.render(
    <div className="felt">
      <div className="opponent pos-left" /><div className="opponent pos-top" /><div className="opponent pos-right" />
      <div className="you-row" /><div className="hand"><div className="hand-slot" /></div>
      <TableCompanions state={state} />
    </div>); });
  await flush();
  const px = Number(host.querySelector('.tc-seat[data-seat="0"] .tc-move svg')?.getAttribute("width"));
  await act(async () => { root.render(<></>); });
  return px;
}

describe("the Stage · Table switch", () => {
  it("reads Stage · Table, labels only, Stage by default", async () => {
    await stage();
    const sw = host.querySelector(".char-view")!;
    expect([...sw.querySelectorAll(".segmented-btn")].map((b) => b.textContent)).toEqual(["Stage", "Table"]);
    expect(sw.textContent).toBe("StageTable");
    expect(option("Stage").getAttribute("aria-pressed")).toBe("true");
    expect(host.querySelector(".char-stage .char-figures svg.cmp")).not.toBeNull();
    expect(host.querySelector(".table-companions")).toBeNull();
  });

  it("in Chinese it reads 展示 · 牌桌", async () => {
    setLanguageChoice("zh-Hans");
    await stage();
    expect([...host.querySelectorAll(".char-view .segmented-btn")].map((b) => b.textContent)).toEqual(["展示", "牌桌"]);
  });

  it("keeps the last choice on this device, and works without storage", async () => {
    await stage();
    await toTable();
    expect(window.localStorage.getItem("shengji.collectionView")).toBe("table");
    act(() => root.unmount());
    root = createRoot(host);
    await stage();
    expect(option("Table").getAttribute("aria-pressed")).toBe("true");
    expect(host.querySelector(".table-companions")).not.toBeNull();
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    try {
      act(() => root.unmount());
      root = createRoot(host);
      await stage();
      expect(option("Stage").getAttribute("aria-pressed")).toBe("true");
      await toTable();
      expect(host.querySelector(".table-companions")).not.toBeNull();
    } finally { get.mockRestore(); set.mockRestore(); }
  });
});

describe("the Table view", () => {
  it.each([[false, 44], [true, 60]])("draws yours at the bottom seat's size at the table (tablet %s: %i px)", async (tab, px) => {
    tablet = tab;
    const seat = await tableSeatSize();
    expect(seat).toBe(px);
    await stage();
    await toTable();
    const fig = host.querySelector(".char-seat .tc-seat .tc-move svg");
    expect(Number(fig?.getAttribute("width"))).toBe(seat);
  });

  it("is the table's own layer: yours alone, tagged You, in the bottom-left corner, with no cards and no nameplate", async () => {
    await stage();
    await toTable();
    expect(host.querySelectorAll(".char-seat .tc-seat")).toHaveLength(1);
    expect(host.querySelector(".tc-seat")?.getAttribute("data-pos")).toBe("bottom");
    expect(host.querySelector(".tc-you")?.textContent).toBe("You");
    expect(host.querySelector(".char-table .felt")).not.toBeNull();
    expect(host.querySelectorAll(".card, .opponent, .hud, .trick-play")).toHaveLength(0);
    expect(host.querySelector(".char-hand")?.children).toHaveLength(1);
    expect(host.querySelector(".char-hand")?.textContent).toBe("");
    const at = /translate\((-?[\d.]+)px, (-?[\d.]+)px\)/.exec(host.querySelector<HTMLElement>(".tc-walk")!.style.transform)!;
    // over the left end of the empty hand line: x by its start, feet clear of a chosen card's lift
    expect(Number(at[1])).toBeLessThan(40);
    expect(Number(at[2])).toBeGreaterThan(80);
  });

  it("keeps the character across a switch and back", async () => {
    await stage();
    await toTable();
    expect(host.querySelector(".tc-move svg.cmp-bun")).not.toBeNull();
    await act(async () => { option("Stage").click(); });
    await flush();
    expect(host.querySelector(".char-figures svg.cmp-bun")).not.toBeNull();
    expect(host.querySelector(".table-companions")).toBeNull();
  });

  it("Hop, Cheer and Big play play the table's moves on yours; the special's chip is a tap on it", async () => {
    await stage();
    await toTable();
    for (const name of ["Hop", "Cheer", "Big play"]) {
      const from = anims.length;
      await act(async () => { chip(name).click(); });
      await flush(40);
      expect(anims.slice(from).some((a) => a.box === "tc-move"), name).toBe(true);
      await flush(2500);
    }
    // the same chip again plays again
    const again = anims.length;
    await act(async () => { chip("Hop").click(); });
    await flush(40);
    await act(async () => { chip("Hop").click(); });
    await flush(40);
    expect(anims.slice(again).filter((a) => a.box === "tc-move")).toHaveLength(2);
    await flush(2500);
    await act(async () => { chip("Steamer pop").click(); });
    await flush(40);
    expect(host.querySelector(".tc-move")?.getAttribute("data-move")).toBe("react");
  });

  it("a tap on the felt walks yours there, as at the table", async () => {
    await stage();
    await toTable();
    const from = anims.length;
    const seat = host.querySelector(".char-seat")!;
    await act(async () => { seat.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: 200, clientY: 120 })); });
    await flush(40);
    expect(anims.slice(from).some((a) => a.box === "tc-walk")).toBe(true);
  });

  it("a tile tap seats yours again, so it comes in its own way", async () => {
    await stage();
    await toTable();
    expect(host.querySelectorAll(".tc-seat")).toHaveLength(1);
    await act(async () => { root.render(<Stage kind="bun" colour="plain" size={176} label="Bun · Plain" moves arrives={1} />); });
    expect(host.querySelectorAll(".tc-seat")).toHaveLength(0);
    await flush(100);
    expect(host.querySelectorAll(".tc-seat")).toHaveLength(1);
  });
});
