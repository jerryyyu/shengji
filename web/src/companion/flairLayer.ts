// Where a store character's pieces are painted: two canvases over one
// felt, `back` under the figures (the trail, the marks) and `front` over
// them (bursts, accents, the glint), so a trail is never in front of a
// figure. One frame loop paints both and runs only while a piece is alive;
// a table at rest draws nothing. Every piece is counted against its seat's
// caps and the felt's, and none starts while the hand is dealt, while the
// page is hidden or under Reduce Motion (which gets still pieces instead).
// A slow device steps the caps down, and back up once it keeps up again.
import { prefersReducedMotion } from "../motion";
import type { Key, Piece } from "./flair";

/** What a piece is for: each has its own cap. */
export type Tag = "trail" | "cue" | "burst" | "shower" | "entrance";
export type Tier = "full" | "half" | "minimal";
type Caps = Record<Tag, number>;
/** The most pieces alive at once: for your own figure, for another seat's,
 *  and on one felt. Half halves each; minimal keeps the mark, the glint and
 *  a short trail for your own figure, one piece a hop. */
export const CAPS: Record<Tier, { own: Caps; other: Caps; felt: number }> = {
  full: { own: { trail: 18, cue: 2, burst: 11, shower: 9, entrance: 9 }, other: { trail: 9, cue: 2, burst: 5, shower: 4, entrance: 4 }, felt: 64 },
  half: { own: { trail: 9, cue: 2, burst: 5, shower: 4, entrance: 4 }, other: { trail: 4, cue: 1, burst: 2, shower: 2, entrance: 2 }, felt: 32 },
  minimal: { own: { trail: 4, cue: 2, burst: 2, shower: 0, entrance: 1 }, other: { trail: 0, cue: 1, burst: 1, shower: 0, entrance: 1 }, felt: 8 },
};

/** What the minimal tier still paints besides your own trail: a character's mark and its glint, never its pieces. */
export const MINIMAL_SHAPES: ReadonlySet<string> = new Set(["blossom", "ripple", "spark"]);
/** Frames watched before the tier is weighed again, and the shares of slow
 *  ones that step it down. */
export const TIER_WINDOW = 180;
export const SLOW_HALF = 0.02;
export const SLOW_MINIMAL = 0.05;
/** A frame is slow past this many refresh intervals, an interval never
 *  taken as shorter than 60 a second: a display at 120 a second that drops
 *  to 60 for a while is on time. */
export const SLOW_INTERVALS = 1.5;
export const SLOWEST_ON_TIME_MS = 1000 / 60;
/** Clean windows in a row before the tier steps back up one. */
export const RECOVER_WINDOWS = 2;
/** A steady gap this long is a display held to 30 a second (Low Power Mode). */
export const LOW_POWER_MS = 30;

/** Watches the gaps between the loop's own frames: half at 2% of a window's
 *  frames slow, minimal at 5% or on a display held to 30 a second, at once;
 *  one tier back up after two clean windows in a row (Low Power Mode turned
 *  off, a slow start that has passed). */
export class TierSampler {
  tier: Tier = "full";
  private gaps: number[] = [];
  private clean = 0;
  note(gap: number): Tier {
    // a gap this long is the loop starting again, not a frame
    if (gap <= 0 || gap > 250) return this.tier;
    this.gaps.push(gap);
    if (this.gaps.length < TIER_WINDOW) return this.tier;
    const sorted = [...this.gaps].sort((a, b) => a - b);
    this.gaps = [];
    // the refresh interval is the usual gap; the median stays it while most frames are on time
    const interval = sorted[Math.floor(sorted.length / 2)];
    const slow = sorted.filter((g) => g > Math.max(interval, SLOWEST_ON_TIME_MS) * SLOW_INTERVALS).length / sorted.length;
    const seen: Tier = interval >= LOW_POWER_MS || slow >= SLOW_MINIMAL ? "minimal" : slow >= SLOW_HALF ? "half" : "full";
    const rank = { full: 0, half: 1, minimal: 2 } as const;
    if (rank[seen] >= rank[this.tier]) {
      this.clean = 0;
      this.tier = seen;
    } else if (++this.clean >= RECOVER_WINDOWS) {
      this.clean = 0;
      this.tier = this.tier === "minimal" ? "half" : "full";
    }
    return this.tier;
  }
}
/** One tier for the page, wherever pieces are painted. */
export const sessionTier = new TierSampler();

interface Live { owner: string; tag: Tag; piece: Piece; t0: number }

const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
/** A piece's state at `t` of its life, between its keys. */
export function stateAt(keys: readonly Key[], t: number): Key {
  if (keys.length === 1 || t <= keys[0].t) return keys[0];
  for (let i = 1; i < keys.length; i++) {
    const a = keys[i - 1], b = keys[i];
    if (t <= b.t) {
      const k = (t - a.t) / Math.max(1e-6, b.t - a.t);
      return { t, x: lerp(a.x, b.x, k), y: lerp(a.y, b.y, k), r: lerp(a.r, b.r, k), sx: lerp(a.sx, b.sx, k), sy: lerp(a.sy, b.sy, k), o: lerp(a.o, b.o, k) };
    }
  }
  return keys[keys.length - 1];
}

/** Draw one piece's shape round the origin, `w` by `h`. */
function shape(ctx: CanvasRenderingContext2D, p: Piece): void {
  const w = p.w / 2, h = p.h / 2;
  ctx.beginPath();
  if (p.shape === "petal" || p.shape === "leaf") {
    // two arcs between its tips: a petal is plump, a leaf slim
    ctx.moveTo(-w, 0);
    ctx.quadraticCurveTo(0, -h * 2, w, 0);
    ctx.quadraticCurveTo(0, h * 2, -w, 0);
    ctx.fillStyle = p.c1;
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(-w, 0);
    ctx.quadraticCurveTo(0, h * 2, w, 0);
    ctx.fillStyle = p.c2;
    ctx.fill();
  } else if (p.shape === "spark") {
    const q = 0.16;
    ctx.moveTo(0, -w); ctx.lineTo(w * q, -w * q); ctx.lineTo(w, 0); ctx.lineTo(w * q, w * q);
    ctx.lineTo(0, w); ctx.lineTo(-w * q, w * q); ctx.lineTo(-w, 0); ctx.lineTo(-w * q, -w * q);
    ctx.closePath();
    ctx.fillStyle = p.c1;
    ctx.fill();
  } else if (p.shape === "blossom") {
    // five petals round the middle, in outline
    ctx.strokeStyle = p.c1;
    ctx.lineWidth = Math.max(1, w * 0.06);
    for (let i = 0; i < 5; i++) {
      const a = (i * 2 * Math.PI) / 5, c = Math.cos(a), s = Math.sin(a);
      const at = (x: number, y: number): [number, number] => [x * c - y * s, x * s + y * c];
      const [x1, y1] = at(-w * 0.26, -w * 0.5), [x2, y2] = at(0, -w * 0.9), [x3, y3] = at(w * 0.26, -w * 0.5);
      ctx.moveTo(0, 0);
      ctx.quadraticCurveTo(x1, y1, x2, y2);
      ctx.quadraticCurveTo(x3, y3, 0, 0);
    }
    ctx.stroke();
  } else if (p.shape === "ripple") {
    ctx.strokeStyle = p.c1;
    ctx.lineWidth = Math.max(1.5, w * 0.12);
    ctx.arc(0, 0, w * 0.9, 0, Math.PI * 2);
    ctx.stroke();
  } else {
    ctx.fillStyle = p.c1;
    ctx.arc(0, 0, w * 0.8, 0, Math.PI * 2);
    ctx.fill();
  }
}

/** The pieces of one felt. `back` and `front` are its canvases, each the
 *  felt's size in CSS px; `clock` and `frame` are the page's unless a test
 *  gives its own. */
export class FlairLayer {
  private live: Live[] = [];
  private stills = new Map<string, readonly Piece[]>();
  private running = 0;
  private last = 0;
  private dpr = 1;
  private size = { w: 0, h: 0 };
  /** While the hand is dealt nothing starts. */
  dealing = false;
  /** With cards on the felt the trail and the cue are drawn fainter. */
  quiet = false;
  dropped = 0;
  private back: HTMLCanvasElement | null;
  private front: HTMLCanvasElement | null;
  private sampler: TierSampler;
  private clock: () => number;
  private frame: (fn: (now: number) => void) => number;
  private cancel: (id: number) => void;
  constructor(back: HTMLCanvasElement | null, front: HTMLCanvasElement | null, sampler: TierSampler = sessionTier,
    clock: () => number = () => performance.now(),
    frame: (fn: (now: number) => void) => number = (fn) => window.requestAnimationFrame(fn),
    cancel: (id: number) => void = (id) => window.cancelAnimationFrame(id)) {
    this.back = back; this.front = front; this.sampler = sampler; this.clock = clock; this.frame = frame; this.cancel = cancel;
    document.addEventListener("visibilitychange", this.seen);
  }
  private seen = () => { if (document.visibilityState === "hidden") this.clear(); };
  get tier(): Tier { return this.sampler.tier; }
  /** Fit both canvases to a felt `w` by `h` CSS px. */
  resize(w: number, h: number): void {
    if (w === this.size.w && h === this.size.h) return;
    this.size = { w, h };
    this.dpr = Math.min(2, typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1);
    for (const c of [this.back, this.front]) {
      if (!c) continue;
      c.width = Math.round(w * this.dpr);
      c.height = Math.round(h * this.dpr);
      c.style.width = `${w}px`;
      c.style.height = `${h}px`;
    }
    this.paint(this.clock());
  }
  /** Pieces alive: all of them, one seat's, or one seat's of one kind. */
  alive(owner?: string, tag?: Tag): number {
    if (owner === undefined) return this.live.length;
    return this.live.filter((l) => l.owner === owner && (tag === undefined || l.tag === tag)).length;
  }
  /** Start `pieces` for `owner` (your own figure when `own`), as many as
   *  its caps and the felt's leave room for; the rest are dropped, never
   *  queued. Returns how many started. */
  spawn(owner: string, own: boolean, tag: Tag, pieces: readonly Piece[]): number {
    if (this.dealing || prefersReducedMotion() || document.visibilityState === "hidden" || (!this.back && !this.front)) return 0;
    const caps = CAPS[this.tier];
    const cap = (own ? caps.own : caps.other)[tag];
    const now = this.clock();
    let started = 0;
    // on the slowest tier your own trail keeps one piece a hop
    const minimal = this.tier === "minimal", trail = minimal && own && tag === "trail";
    for (const piece of pieces) {
      if (minimal && (trail ? started > 0 : !MINIMAL_SHAPES.has(piece.shape))) { this.dropped++; continue; }
      if (this.alive(owner, tag) >= cap || this.live.length >= caps.felt) { this.dropped++; continue; }
      const faint = this.quiet && (tag === "trail" || tag === "cue");
      this.live.push({ owner, tag, t0: now, piece: faint ? { ...piece, keys: piece.keys.map((k) => ({ ...k, o: k.o * 0.55 })) } : piece });
      started++;
    }
    if (started && !this.running) { this.last = 0; this.running = this.frame(this.tick); }
    return started;
  }
  /** Under Reduce Motion: `owner`'s still pieces, painted once (null takes them away). */
  rest(owner: string, pieces: readonly Piece[] | null): void {
    if (pieces && pieces.length) this.stills.set(owner, pieces); else if (!this.stills.delete(owner)) return;
    if (!this.running) this.paint(this.clock());
  }
  /** Take every moving piece off, at once. */
  clear(): void {
    this.live = [];
    if (this.running) { this.cancel(this.running); this.running = 0; }
    this.paint(this.clock());
  }
  destroy(): void {
    document.removeEventListener("visibilitychange", this.seen);
    this.stills.clear();
    this.clear();
  }
  private tick = (now: number) => {
    if (this.last) this.sampler.note(now - this.last);
    this.last = now;
    this.live = this.live.filter((l) => now - l.t0 < l.piece.delay + l.piece.ms);
    this.paint(now);
    this.running = this.live.length ? this.frame(this.tick) : 0;
  };
  private paint(now: number): void {
    for (const [canvas, depth] of [[this.back, "back"], [this.front, "front"]] as const) {
      const ctx = canvas?.getContext?.("2d");
      if (!canvas || !ctx) continue;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const draw = (p: Piece, k: Key) => {
        if (k.o <= 0.004 || k.sx === 0 || k.sy === 0) return;
        const a = (k.r * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a), d = this.dpr;
        ctx.setTransform(c * k.sx * d, s * k.sx * d, -s * k.sy * d, c * k.sy * d, k.x * d, k.y * d);
        ctx.globalAlpha = Math.min(1, k.o);
        shape(ctx, p);
      };
      for (const pieces of this.stills.values()) for (const p of pieces) if (p.depth === depth) draw(p, p.keys[0]);
      for (const l of this.live) {
        if (l.piece.depth !== depth) continue;
        const t = (now - l.t0 - l.piece.delay) / l.piece.ms;
        if (t >= 0 && t < 1) draw(l.piece, stateAt(l.piece.keys, t));
      }
      ctx.globalAlpha = 1;
    }
  }
}
