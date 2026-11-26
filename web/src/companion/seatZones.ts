// Where a companion may stand by its player's nameplate (Individual view):
// a home spot beside the nameplate and the small zone round it that it
// walks in. Pure: the table measures its rects, in px relative to the felt,
// and passes them here. A spot is allowed only where the figure (and the
// "You" tag over your own) clears every obstacle: the played cards, the
// hand, the buttons, the HUD and the nameplates. The zone is worked out
// again whenever those move, so it follows the cards played.

export interface Rect { x: number; y: number; w: number; h: number }
export interface Spot { x: number; y: number }
/** Where a seat is drawn from the viewer's chair. */
export type SeatPos = "left" | "top" | "right" | "bottom";

export interface Layout {
  /** The felt's size. */
  felt: { w: number; h: number };
  /** Each seat's nameplate (its opponent panel); `bottom` is you, who has none on a phone. */
  plates: Partial<Record<SeatPos, Rect>>;
  /** Your name line, where the layout draws one (a tablet or a desktop window). */
  tagline: Rect | null;
  /** Your row of controls above the hand. */
  row: Rect | null;
  /** What no figure may cover. */
  obstacles: readonly Rect[];
}

export interface Zone {
  /** The spot the figure stands on at rest, or null when no spot near its nameplate is clear. */
  home: Spot | null;
  /** Every clear spot it may walk to, `home` among them. */
  spots: Spot[];
}

/** The room the figure keeps from everything else, in px. */
const GAP = 3;
/** The height of the "You" tag over your own companion. */
export const TAG_H = 16;

export const meets = (a: Rect, b: Rect): boolean =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/** How far a figure rises off its spot as it hops, walks or sways, as a share of its size. */
export const LIFT = 0.15;

/** The box a figure of `size` standing at `s` may take as it moves there,
 *  its tag and its rise included. */
export const figureBox = (s: Spot, size: number, tag: boolean): Rect => {
  const up = Math.ceil(size * LIFT) + (tag ? TAG_H : 0) + GAP;
  return { x: s.x - GAP - Math.ceil(size * 0.05), y: s.y - up, w: size * 1.1 + 2 * GAP, h: size + up + GAP };
};

/** Whether a figure at `s` clears every obstacle and stays on the felt. */
export function clear(s: Spot, size: number, tag: boolean, layout: Layout): boolean {
  const box = figureBox(s, size, tag);
  if (box.x < 0 || box.y < 0 || box.x + box.w > layout.felt.w || box.y + box.h > layout.felt.h) return false;
  return !layout.obstacles.some((o) => meets(box, o));
}

/** The spot a seat's figure would stand on beside its nameplate, before
 *  any obstacle is weighed: under a side seat's nameplate, to the right of
 *  your partner's, and for you beside your name line or, on a phone, above
 *  your hand at the left. */
export function ideal(pos: SeatPos, size: number, layout: Layout): Spot | null {
  const p = layout.plates[pos];
  if (pos === "left") return p ? { x: p.x + 10, y: p.y + p.h + 4 } : null;
  if (pos === "right") return p ? { x: p.x + p.w - 10 - size, y: p.y + p.h + 4 } : null;
  if (pos === "top") return p ? { x: p.x + p.w + 8, y: Math.max(4, p.y + p.h - size + 8) } : null;
  const tag = layout.tagline;
  if (tag && tag.w > 0) return { x: tag.x + tag.w + 10, y: tag.y + tag.h - size };
  const row = layout.row;
  const left = layout.plates.left;
  const bottom = row ? row.y + row.h : layout.felt.h - 120;
  return { x: (left ? left.x : 8) + 72, y: bottom - size };
}

/** A seat's zone: the clear spots on a grid round its ideal spot, two
 *  figures wide either way and half a figure up or down, and the clear spot
 *  nearest the ideal as its home. */
export function zoneFor(pos: SeatPos, size: number, layout: Layout, tag = pos === "bottom"): Zone {
  const at = ideal(pos, size, layout);
  if (!at) return { home: null, spots: [] };
  const step = Math.max(4, Math.round(size / 4));
  const spots: Spot[] = [];
  for (let dy = -size / 2; dy <= size / 2 + 0.01; dy += step) {
    for (let dx = -2 * size; dx <= 2 * size + 0.01; dx += step) {
      const s = { x: Math.round(at.x + dx), y: Math.round(at.y + dy) };
      if (clear(s, size, tag, layout)) spots.push(s);
    }
  }
  let home: Spot | null = null;
  let best = Infinity;
  for (const s of spots) {
    const d = Math.hypot(s.x - at.x, s.y - at.y);
    if (d < best) { best = d; home = s; }
  }
  return { home, spots };
}

/** The next spot a walk goes to: a clear one of the zone at least half a
 *  figure from `from`, chosen by `rand` (0 to 1); null when there is none. */
export function nextSpot(zone: Zone, from: Spot, size: number, rand: number): Spot | null {
  const far = zone.spots.filter((s) => Math.hypot(s.x - from.x, s.y - from.y) >= size / 2);
  if (far.length === 0) return null;
  return far[Math.min(far.length - 1, Math.floor(rand * far.length))];
}

/** The clear spot of the zone nearest `s`: where a figure goes when cards
 *  land on it. */
export function nearest(zone: Zone, s: Spot): Spot | null {
  let out: Spot | null = null;
  let best = Infinity;
  for (const z of zone.spots) {
    const d = Math.hypot(z.x - s.x, z.y - s.y);
    if (d < best) { best = d; out = z; }
  }
  return out;
}

/** Whether a walk from `a` to `b` stays clear the whole way, checked a
 *  quarter figure at a time. */
export function pathClear(a: Spot, b: Spot, size: number, tag: boolean, layout: Layout): boolean {
  const steps = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y) / Math.max(4, size / 4)));
  for (let i = 0; i <= steps; i++) {
    const s = { x: a.x + ((b.x - a.x) * i) / steps, y: a.y + ((b.y - a.y) * i) / steps };
    if (!clear(s, size, tag, layout)) return false;
  }
  return true;
}
