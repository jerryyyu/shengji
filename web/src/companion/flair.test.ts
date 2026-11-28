// The companions' character (every companion's gait, habit and way in) and
// a store character's material (its pieces, where they may go, and the
// layer that paints and counts them).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ARRIVES, GAITS, GOLD, LUNGERS, MATERIALS, PLAIN_GAIT, QUIRKS, accentPieces, burstPieces, cuePieces, droopPiece, entrancePieces, gaitFrames, materialOf,
  restPieces, showerPieces, trailPieces, walkAt } from "./flair";
import type { Piece, Stance } from "./flair";
import { CAPS, FlairLayer, MINIMAL_SHAPES, SLOW_HALF, SLOW_MINIMAL, TIER_WINDOW, TierSampler, stateAt } from "./flairLayer";
import { COMPANION_KINDS, COMPANION_PRODUCTS, COMPANIONS, FREE_KINDS } from "./look";

const stance = (over: Partial<Stance> = {}): Stance => ({ x: 300, y: 200, px: 44, dir: 1, colour: "", gold: false, ...over });
const paid = COMPANION_KINDS.filter((k) => COMPANION_PRODUCTS[k]);
/** A stream of numbers that is the same every run. */
const seeded = (seed = 7) => { let s = seed; return () => { s = (s * 1664525 + 1013904223) % 4294967296; return s / 4294967296; }; };

describe("every companion's character", () => {
  it("each companion has a gait, a habit and a way in of its own", () => {
    for (const k of COMPANION_KINDS) {
      expect(GAITS[k].steps.length, k).toBeGreaterThanOrEqual(3);
      expect(QUIRKS[k].frames.length, k).toBeGreaterThanOrEqual(4);
      expect(ARRIVES[k].length, k).toBeGreaterThanOrEqual(1);
    }
    expect(new Set(COMPANION_KINDS.map((k) => JSON.stringify(GAITS[k].steps))).size).toBe(COMPANION_KINDS.length);
    expect(new Set(COMPANION_KINDS.map((k) => JSON.stringify(QUIRKS[k].frames))).size).toBe(COMPANION_KINDS.length);
  });

  it("a gait, a habit and a way in set only a transform (a way in its opacity too), and each starts and ends on the ground at its own size", () => {
    const keys = (frames: readonly Keyframe[]) => [...new Set(frames.flatMap((f) => Object.keys(f)))].filter((p) => p !== "offset").sort();
    for (const k of COMPANION_KINDS) {
      expect(keys(gaitFrames(GAITS[k], 1)), k).toEqual(["transform"]);
      expect(keys(QUIRKS[k].frames), k).toEqual(["transform"]);
      expect(String(QUIRKS[k].frames[0].transform)).toBe("translateY(0%) rotate(0deg) scale(1, 1)");
      expect(String(QUIRKS[k].frames[QUIRKS[k].frames.length - 1].transform)).toBe("translateY(0%) rotate(0deg) scale(1, 1)");
      for (const a of ARRIVES[k]) {
        expect(keys(a.frames), a.name).toEqual(["opacity", "transform"]);
        expect(a.frames[0].opacity, a.name).toBe(0);
        expect(String(a.frames[a.frames.length - 1].transform), a.name).toBe("translateY(0%) rotate(0deg) scale(1, 1)");
      }
      const steps = GAITS[k].steps;
      expect(steps[0][0], k).toBe(0);
      expect(steps[steps.length - 1][0], k).toBe(0);
    }
  });

  it("a gait faces the way it walks, and the pace is the walk's: a step is a whole share of 520 ms or twice it", () => {
    expect(String(gaitFrames(PLAIN_GAIT, -1)[1].transform)).toBe("scaleX(-1) translateY(-12%) rotate(0deg) scale(1, 1)");
    for (const k of COMPANION_KINDS) expect([260, 520, 1040], k).toContain(GAITS[k].step);
  });
});

describe("a store character's material", () => {
  it("every store character has one, with a trail, a cue, a mark and an accent, a tint for each of its colours; a free companion has none", () => {
    expect(paid.length).toBeGreaterThan(0);
    for (const k of paid) {
      const m = materialOf(k)!;
      expect(m, k).not.toBeNull();
      for (const colour of COMPANIONS[k]) expect(m.tints[colour], `${k}/${colour}`).toHaveLength(2);
      expect(m.accent.times.length, k).toBeGreaterThan(0);
      expect(cuePieces(m, stance()).length, k).toBeGreaterThan(0);
    }
    for (const k of FREE_KINDS) expect(materialOf(k), k).toBeNull();
    expect(Object.keys(MATERIALS).sort()).toEqual([...paid].sort());
    for (const k of LUNGERS) expect(paid).toContain(k);
  });

  it("no two store characters share a mark or a cue", () => {
    const marks = paid.map((k) => materialOf(k)!.mark), cues = paid.map((k) => cuePieces(materialOf(k)!, stance()).map((p) => p.shape).join());
    expect(new Set(marks).size).toBe(paid.length);
    expect(new Set(cues).size).toBe(paid.length);
  });

  it.each([[1, 0], [-1, 0], [0, 1], [0, -1], [0.6, 0.8], [-0.6, -0.8]])(
    "walking along (%f, %f) every trail piece starts and stays behind the figure's middle along the way it walks, on the layer under the figures", (ux, uy) => {
      for (const k of paid) for (let serial = 0; serial < 12; serial++) {
        const s = stance({ dir: ux < 0 ? -1 : 1 });
        const pieces = trailPieces(materialOf(k)!, s, { x: ux, y: uy }, 3, serial * 3, seeded(serial + 1));
        expect(pieces).toHaveLength(3);
        for (const p of pieces) {
          expect(p.depth).toBe("back");
          // every state of it is behind the figure's middle along the way it walks
          for (const key of p.keys) {
            const along = (key.x - s.x) * ux + (key.y - (s.y - s.px / 2)) * uy;
            expect(along, `${k} ${serial} t=${key.t}`).toBeLessThan(0);
          }
          // and it lands on the felt well behind its feet
          const land = p.keys[p.keys.length - 1];
          expect((land.x - s.x) * ux + (land.y - s.y) * uy).toBeLessThan(-s.px * 0.55);
        }
        // one at a time
        expect(new Set(pieces.map((p) => p.delay)).size).toBe(pieces.length);
      }
    });

  it("from the level its team stops growing at, every third trail piece is gold", () => {
    const m = materialOf("lamb")!;
    const tints = (gold: boolean) => [0, 1, 2, 3].flatMap((n) => trailPieces(m, stance({ gold, colour: "newyear" }), { x: 1, y: 0 }, 3, n * 3, seeded()).map((p) => p.c1));
    expect(tints(false)).not.toContain(GOLD[0]);
    expect(tints(true).filter((c) => c === GOLD[0])).toHaveLength(4);
  });

  it("a burst starts on a ring outside the figure, in two lobes clear of its jump, one piece at a time", () => {
    for (const k of paid) {
      const s = stance(), m = materialOf(k)!;
      const pieces = burstPieces(m, s, 7, 300, seeded()).filter((p) => p.shape === m.shape);
      expect(pieces).toHaveLength(7);
      for (const p of pieces) {
        const dx = p.keys[0].x - s.x, dy = p.keys[0].y - (s.y - s.px * 0.5);
        expect(Math.hypot(dx, dy), k).toBeGreaterThanOrEqual(s.px * 0.59);
        // not over its head, where it jumps
        expect(Math.abs(dx), k).toBeGreaterThan(s.px * 0.2);
        expect(p.keys[1].y).toBeLessThan(p.keys[0].y);
      }
      expect(new Set(pieces.map((p) => p.delay)).size).toBe(7);
      expect(pieces.filter((p) => p.keys[0].x > s.x)).toHaveLength(4);
    }
  });

  it("a shower falls either side of the figure, never onto it", () => {
    for (const k of paid) {
      const s = stance(), m = materialOf(k)!;
      for (const p of showerPieces(m, s, 6, seeded()).filter((q) => q.shape === m.shape)) {
        for (const key of p.keys) expect(Math.abs(key.x - s.x), k).toBeGreaterThanOrEqual(s.px * 0.7 - 0.01);
      }
    }
  });

  it.each([1, -1] as const)("facing %i, the special's accent fans away from the body, ahead of where it faces, further on by the lunge", (dir) => {
    for (const k of paid) {
      const s = stance({ dir }), m = materialOf(k)!;
      for (const reach of [0, 22]) for (const at of m.accent.times) {
        const pieces = accentPieces(m, s, reach, at, true, seeded());
        expect(pieces).toHaveLength(m.accent.n);
        for (const p of pieces) for (const key of p.keys) expect((key.x - s.x) * dir, k).toBeGreaterThan(s.px * 0.4 + reach);
        expect(pieces[0].delay).toBe(at);
      }
      expect(accentPieces(m, s, 0, 0, false).length).toBe(Math.ceil(m.accent.n / 2));
    }
  });

  it("an entrance's pieces stop outside the figure; the lost trick's one piece falls beside it; Reduce Motion's lie at its feet", () => {
    const s = stance(), lamb = materialOf("lamb")!;
    const spiral = entrancePieces(lamb, s, 8, seeded()).filter((p) => p.shape === "petal");
    expect(spiral).toHaveLength(7);
    for (const p of spiral) {
      const end = p.keys[p.keys.length - 1];
      expect(Math.hypot(end.x - s.x, (end.y - (s.y - s.px * 0.5)) / 0.8)).toBeGreaterThanOrEqual(s.px * 0.6);
    }
    for (const k of paid) {
      expect(entrancePieces(materialOf(k)!, s, 8, seeded()).length, k).toBeLessThanOrEqual(9);
      expect(entrancePieces(materialOf(k)!, s, 4, seeded()).length, k).toBeLessThanOrEqual(4);
      const fall = droopPiece(materialOf(k)!, s);
      expect(fall).toHaveLength(1);
      expect(Math.abs(fall[0].keys[0].x - s.x)).toBeGreaterThanOrEqual(s.px * 0.5);
      const rest = restPieces(materialOf(k)!, s);
      expect(rest).toHaveLength(3);
      for (const p of rest) { expect(p.keys).toHaveLength(1); expect(p.depth).toBe("back"); }
    }
  });

  it("a walk's place at any share of its time is worked out, not read: it starts, ends and turns its corner where the walk does", () => {
    const a = { x: 10, y: 10 }, b = { x: 110, y: 60 }, v = { x: 110, y: 10 };
    expect(walkAt(a, b, 0).x).toBeCloseTo(10, 3);
    expect(walkAt(a, b, 1).x).toBeCloseTo(110, 3);
    expect(walkAt(a, b, 0.5).x).toBeCloseTo(60, 1);
    expect(walkAt(a, b, 0.25).x).toBeLessThan(35);
    const mid = walkAt(a, b, 0.5, v, 2 / 3);
    expect(mid.y).toBeCloseTo(10, 3);
    expect(mid.x).toBeCloseTo(85, 0);
  });
});

describe("the layer that paints the pieces", () => {
  let now = 0;
  let frames: ((t: number) => void)[] = [];
  let hidden = false;
  let reduced = false;
  const realMatch = window.matchMedia;
  const ctx = () => ({ setTransform: vi.fn(), clearRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), quadraticCurveTo: vi.fn(), closePath: vi.fn(),
    fill: vi.fn(), stroke: vi.fn(), arc: vi.fn(), globalAlpha: 1, fillStyle: "", strokeStyle: "", lineWidth: 1 });
  const canvas = () => { const c = ctx(); return { el: { width: 0, height: 0, style: {} as Record<string, string>, getContext: () => c } as unknown as HTMLCanvasElement, c }; };
  const make = (sampler = new TierSampler()) => {
    const back = canvas(), front = canvas();
    const layer = new FlairLayer(back.el, front.el, sampler, () => now, (fn) => { frames.push(fn); return frames.length; }, () => { frames = []; });
    layer.resize(600, 300);
    return { layer, back, front };
  };
  /** Run the loop to `to` ms, a frame every 16. */
  const run = (to: number) => { while (now < to) { now += 16; const due = frames; frames = []; for (const fn of due) fn(now); } };
  const piece = (over: Partial<Piece> = {}): Piece => ({ shape: "petal", depth: "back", w: 11, h: 8, c1: "#f00", c2: "#a00", ms: 1000, delay: 0,
    keys: [{ t: 0, x: 0, y: 0, r: 0, sx: 1, sy: 1, o: 1 }, { t: 1, x: 10, y: 10, r: 90, sx: 1, sy: 1, o: 0 }], ...over });
  const many = (n: number, over: Partial<Piece> = {}) => Array.from({ length: n }, () => piece(over));
  beforeEach(() => {
    now = 1000; frames = []; hidden = false; reduced = false;
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => (hidden ? "hidden" : "visible"));
    window.matchMedia = ((q: string) => ({ matches: reduced && q.includes("reduce"), addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
  });
  afterEach(() => { vi.restoreAllMocks(); window.matchMedia = realMatch; });

  it("never holds more than its caps: 18 of a trail for your own figure, 9 for another's, 64 on the felt; the rest are dropped, not queued", () => {
    const { layer } = make();
    expect(layer.spawn("0", true, "trail", many(40))).toBe(18);
    expect(layer.spawn("1", false, "trail", many(40))).toBe(9);
    expect(layer.spawn("0", true, "burst", many(40))).toBe(11);
    expect(layer.spawn("1", false, "burst", many(40))).toBe(5);
    expect(layer.spawn("0", true, "shower", many(40))).toBe(9);
    expect(layer.spawn("0", true, "cue", many(40))).toBe(2);
    expect(layer.spawn("0", true, "entrance", many(40))).toBe(9);
    for (const seat of ["2", "3"]) for (const tag of ["trail", "burst", "shower", "entrance", "cue"] as const) layer.spawn(seat, false, tag, many(40));
    expect(layer.alive()).toBeLessThanOrEqual(CAPS.full.felt);
    expect(layer.alive()).toBe(64);
    expect(layer.spawn("3", false, "cue", many(2))).toBe(0);
    expect(layer.dropped).toBeGreaterThan(0);
    // a piece that has ended makes room
    run(now + 1100);
    expect(layer.alive()).toBe(0);
    expect(layer.spawn("0", true, "trail", many(3))).toBe(3);
  });

  it("starts nothing while the hand is dealt, on a hidden page or under Reduce Motion", () => {
    const { layer } = make();
    layer.dealing = true;
    expect(layer.spawn("0", true, "trail", many(3))).toBe(0);
    layer.dealing = false;
    hidden = true;
    expect(layer.spawn("0", true, "burst", many(3))).toBe(0);
    hidden = false;
    reduced = true;
    expect(layer.spawn("0", true, "entrance", many(3))).toBe(0);
    expect(frames).toHaveLength(0);
    reduced = false;
    expect(layer.spawn("0", true, "trail", many(3))).toBe(3);
  });

  it("a page that goes hidden takes every piece off and stops the loop", () => {
    const { layer } = make();
    layer.spawn("0", true, "trail", many(5));
    expect(frames).toHaveLength(1);
    hidden = true;
    document.dispatchEvent(new Event("visibilitychange"));
    expect(layer.alive()).toBe(0);
    expect(frames).toHaveLength(0);
    layer.destroy();
  });

  it("the loop runs only while a piece is alive: a table at rest asks for no frame", () => {
    const { layer, back } = make();
    expect(frames).toHaveLength(0);
    layer.spawn("0", true, "trail", many(2, { ms: 300 }));
    expect(frames).toHaveLength(1);
    run(now + 200);
    expect(frames).toHaveLength(1);
    expect(back.c.fill).toHaveBeenCalled();
    run(now + 200);
    expect(layer.alive()).toBe(0);
    expect(frames).toHaveLength(0);
  });

  it("a trail piece is painted on the canvas under the figures only; a burst piece on the one over them", () => {
    const { layer, back, front } = make();
    layer.spawn("0", true, "trail", many(1));
    run(now + 32);
    expect(back.c.fill).toHaveBeenCalled();
    expect(front.c.fill).not.toHaveBeenCalled();
    layer.spawn("0", true, "burst", many(1, { depth: "front" }));
    run(now + 32);
    expect(front.c.fill).toHaveBeenCalled();
  });

  it("with cards in play the trail and the cue are fainter; a burst is not", () => {
    const { layer, back, front } = make();
    layer.quiet = true;
    const alphas = (c: ReturnType<typeof ctx>) => { const seen: number[] = []; Object.defineProperty(c, "globalAlpha", { set: (v: number) => { seen.push(v); }, get: () => 1 }); return seen; };
    const under = alphas(back.c), over = alphas(front.c);
    layer.spawn("0", true, "trail", many(1, { keys: [{ t: 0, x: 0, y: 0, r: 0, sx: 1, sy: 1, o: 1 }] }));
    layer.spawn("0", true, "burst", many(1, { depth: "front", keys: [{ t: 0, x: 0, y: 0, r: 0, sx: 1, sy: 1, o: 1 }] }));
    run(now + 16);
    expect(under.filter((v) => v !== 1)[0]).toBeCloseTo(0.55, 5);
    expect(over[0]).toBe(1);
  });

  it("under Reduce Motion a store character's still pieces are painted once, with no loop", () => {
    const { layer, back } = make();
    reduced = true;
    layer.rest("0", restPieces(materialOf("lamb")!, stance()));
    expect(frames).toHaveLength(0);
    expect(back.c.fill).toHaveBeenCalledTimes(6);
    layer.rest("0", null);
    expect(frames).toHaveLength(0);
  });

  it("a slow device steps the caps down and never back up: half at 2% of frames slow, the mark and the glint only at 5% or a display held to 30 a second", () => {
    const window = (slow: number, gap = 16.7) => Array.from({ length: TIER_WINDOW }, (_, i) => (i < Math.round(slow * TIER_WINDOW) ? gap * 2 : gap));
    const fed = (gaps: number[][]) => { const s = new TierSampler(); for (const w of gaps) for (const g of w) s.note(g); return s; };
    expect(fed([window(0.01)]).tier).toBe("full");
    expect(fed([window(SLOW_HALF)]).tier).toBe("half");
    expect(fed([window(SLOW_MINIMAL)]).tier).toBe("minimal");
    expect(fed([window(0, 33.4)]).tier).toBe("minimal");
    expect(fed([window(SLOW_HALF), window(0), window(0)]).tier).toBe("half");
    expect(fed([window(SLOW_MINIMAL), window(0)]).tier).toBe("minimal");
    // a display at 120 a second is weighed against its own interval
    expect(fed([window(0, 8.3)]).tier).toBe("full");
    const half = new TierSampler();
    half.tier = "half";
    const { layer } = make(half);
    expect(layer.spawn("0", true, "trail", many(40))).toBe(9);
    expect(layer.spawn("1", false, "burst", many(40))).toBe(2);
    const least = new TierSampler();
    least.tier = "minimal";
    const low = make(least).layer;
    expect(low.spawn("0", true, "trail", many(40))).toBe(0);
    expect(low.spawn("0", true, "shower", many(40))).toBe(0);
    expect(low.spawn("0", true, "burst", many(40, { shape: "blossom" }))).toBe(2);
    for (const tier of ["half", "minimal"] as const) for (const who of ["own", "other"] as const) for (const tag of ["trail", "cue", "burst", "shower", "entrance"] as const) {
      expect(CAPS[tier][who][tag]).toBeLessThanOrEqual(CAPS.full[who][tag]);
    }
  });

  it("on the slowest tier only a character's mark and its glint are painted: no petal or leaf of an entrance, a burst, an accent or a trail", () => {
    const least = new TierSampler();
    least.tier = "minimal";
    const fill = (who: string, tag: "entrance" | "burst" | "cue" | "trail" | "shower", pieces: Piece[]) => make(least).layer.spawn(who, true, tag, pieces);
    const lamb = materialOf("lamb")!, panda = materialOf("panda")!, s = stance();
    // the Lamb's entrance is its blossom ring alone; the Panda's (ink and leaves) paints nothing
    expect(fill("0", "entrance", entrancePieces(lamb, s, 8, seeded()))).toBe(1);
    expect(fill("0", "entrance", entrancePieces(panda, s, 8, seeded()))).toBe(0);
    // a burst is its mark: one blossom ring, the two ink ripples
    expect(fill("0", "burst", burstPieces(lamb, s, 7, 0, seeded()))).toBe(1);
    expect(fill("0", "burst", burstPieces(panda, s, 7, 0, seeded()))).toBe(2);
    // an accent is petals or leaves only, a trail and a shower likewise
    for (const m of [lamb, panda]) for (const at of m.accent.times) expect(fill("0", "burst", accentPieces(m, s, 0, at, true, seeded()))).toBe(0);
    expect(fill("0", "trail", trailPieces(lamb, s, { x: 1, y: 0 }, 3, 0, seeded()))).toBe(0);
    expect(fill("0", "shower", showerPieces(lamb, s, 6, seeded()))).toBe(0);
    // the cue stays: the horn's glint, the ripple under the Panda
    expect(fill("0", "cue", cuePieces(lamb, s))).toBe(2);
    expect(fill("0", "cue", cuePieces(panda, s))).toBe(2);
    for (const shape of ["petal", "leaf", "ink"]) expect(MINIMAL_SHAPES.has(shape)).toBe(false);
  });

  it("a piece's state between its keys is a straight line between them", () => {
    const keys = piece().keys;
    expect(stateAt(keys, 0.5)).toMatchObject({ x: 5, y: 5, r: 45, o: 0.5 });
    expect(stateAt(keys, 0)).toBe(keys[0]);
    expect(stateAt(keys, 2)).toBe(keys[1]);
  });
});
