// Where a companion may stand by its player's nameplate (Individual view):
// a home spot beside the nameplate and the small zone round it that it
// walks in. Pure: the table measures its rects, in px relative to the felt,
// and passes them here. A spot is allowed only where the figure (and the
// "You" tag over your own) clears every obstacle: the played cards and
// their LEAD / WINS labels, the hand (with room for a chosen card's lift),
// the buttons, the HUD and the nameplates, and no two seats' zones meet.
// The zone is worked out again whenever those move, so it follows the cards
// played. A tap on the felt finds the clear spot nearest it (`nearestClear`).

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
  /** The first card of your hand, where a phone stands your own companion. */
  hand?: Rect | null;
  /** The felt between the screen's safe-area edges, where a figure may stand. */
  safe?: { x0: number; x1: number };
  /** Of the obstacles, the ones that stay put while a hand is dealt (your
   *  name pill, your row's controls): a figure the deal holds still steps
   *  off these at once. */
  fixed?: Rect[];
  /** A phone's table: no name line of its own (`tagline` is only the banker's
   *  crown and turn chips), and a full hand starts at the safe left edge. */
  phone?: boolean;
  /** What no figure may cover. */
  obstacles: readonly Rect[];
}

export interface Zone {
  /** The spot the figure stands on at rest, or null when no spot near its nameplate is clear. */
  home: Spot | null;
  /** Every clear spot it may walk to, `home` among them. */
  spots: Spot[];
  /** The size the figure is drawn at here: the size asked for, or a step
   *  smaller where its corner is too cramped for it (`zonesFor`). */
  size?: number;
}

/** The room the figure keeps from everything else, in px. */
const GAP = 3;
/** The height of the "You" tag over your own companion. */
export const TAG_H = 16;
/** How far a chosen card rises out of the hand. */
export const HAND_LIFT = 20;

export const meets = (a: Rect, b: Rect): boolean =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/** How far a figure rises off its spot as it hops, walks, sways or cheers
 *  (the cheer's top), as a share of its size: no move rises further. */
export const LIFT = 0.15;

/** The box a figure of `size` standing at `s` may take as it moves there,
 *  its tag and its rise included. */
export const figureBox = (s: Spot, size: number, tag: boolean): Rect => {
  const up = Math.ceil(size * LIFT) + (tag ? TAG_H : 0) + GAP;
  return { x: s.x - GAP - Math.ceil(size * 0.05), y: s.y - up, w: size * 1.1 + 2 * GAP, h: size + up + GAP };
};

/** Whether a figure at `s` clears every obstacle and stays on the felt. */
export function clear(s: Spot, size: number, tag: boolean, layout: Layout): boolean {
  return clearBox(figureBox(s, size, tag), layout);
}
/** Whether `box` clears every obstacle and stays on the felt. */
export function clearBox(box: Rect, layout: Layout): boolean {
  if (box.x < 0 || box.y < 0 || box.x + box.w > layout.felt.w || box.y + box.h > layout.felt.h) return false;
  if (layout.safe && (box.x < layout.safe.x0 || box.x + box.w > layout.safe.x1)) return false;
  return !layout.obstacles.some((o) => meets(box, o));
}

/** The spot a seat's figure would stand on beside its nameplate, before
 *  any obstacle is weighed: under a side seat's nameplate, to the right of
 *  your partner's, and for you beside your name line or, on a phone (no
 *  nameplate of your own), over the left end of your hand, clear of a chosen
 *  card's lift. A phone's is over where a full hand starts (the safe left
 *  edge), so it holds still while the hand is dealt and as it empties, and
 *  the banker's crown chip is not a name line there. */
export function ideal(pos: SeatPos, size: number, layout: Layout): Spot | null {
  const p = layout.plates[pos];
  if (pos === "left") return p ? { x: p.x + 10, y: p.y + p.h + 4 } : null;
  if (pos === "right") return p ? { x: p.x + p.w - 10 - size, y: p.y + p.h + 4 } : null;
  if (pos === "top") return p ? { x: p.x + p.w + 8, y: Math.max(4, p.y + p.h - size + 8) } : null;
  const tag = nameLine(layout);
  if (tag) return { x: tag.x + tag.w + 10, y: tag.y + tag.h - size };
  const hand = layout.hand;
  if (hand && hand.w > 0) return { x: handLeft(layout, hand) + 4, y: hand.y - HAND_LIFT - GAP - size };
  const row = layout.row;
  const left = layout.plates.left;
  const bottom = row ? row.y + row.h : layout.felt.h - 120;
  return { x: (left ? left.x : 8) + 72, y: bottom - size };
}

/** Your name line, where the layout has one: never on a phone. */
const nameLine = (layout: Layout): Rect | null => (!layout.phone && layout.tagline && layout.tagline.w > 0 ? layout.tagline : null);
/** Where your hand's left end is: on a phone, where a full hand starts. */
const handLeft = (layout: Layout, hand: Rect): number => (layout.phone && layout.safe ? layout.safe.x0 : hand.x);

/** Where else a seat's figure may stand when its own corner is taken: by
 *  a side seat's nameplate on its inner side or above it, by your partner's
 *  on its left; yours over or beside your name line, or on the open felt
 *  left of your hand. */
export function fallbacks(pos: SeatPos, size: number, layout: Layout): Spot[] {
  if (pos === "bottom") {
    // yours: over your name line, beside it, then the open felt left of your hand, then over the hand's left end
    const out: Spot[] = [];
    const tag = nameLine(layout);
    if (tag) out.push({ x: tag.x, y: tag.y - 6 - size }, { x: tag.x - 10 - size, y: tag.y + tag.h - size });
    const hand = layout.hand;
    if (hand && hand.w > 0) {
      out.push({ x: handLeft(layout, hand) - size - 14, y: hand.y + 8 });
      if (tag) out.push({ x: hand.x + 4, y: hand.y - HAND_LIFT - GAP - size });
    }
    return out;
  }
  const p = layout.plates[pos];
  if (!p) return [];
  if (pos === "left") return [{ x: p.x + p.w + 4, y: p.y + p.h - size }, { x: p.x + 10, y: p.y - 4 - size }];
  if (pos === "right") return [{ x: p.x - 4 - size, y: p.y + p.h - size }, { x: p.x + p.w - 10 - size, y: p.y - 4 - size }];
  return [{ x: p.x - 8 - size, y: Math.max(4, p.y + p.h - size + 8) }];
}

/** A seat's zone: the clear spots on a grid round its ideal spot, two
 *  figures wide either way and half a figure up or down, and the clear spot
 *  nearest the ideal as its home. */
export function zoneFor(pos: SeatPos, size: number, layout: Layout, tag = pos === "bottom"): Zone {
  return zoneAt(ideal(pos, size, layout), size, layout, tag);
}

function zoneAt(at: Spot | null, size: number, layout: Layout, tag: boolean, wide = 2, high = 0.5): Zone {
  if (!at) return { home: null, spots: [] };
  const step = Math.max(4, Math.round(size / 4));
  const spots: Spot[] = [];
  for (let dy = -high * size; dy <= high * size + 0.01; dy += step) {
    for (let dx = -wide * size; dx <= wide * size + 0.01; dx += step) {
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

/** How far a figure wanders from a spot a tap chose, either way, in
 *  figures across and up or down. */
export const TAPPED_WIDE = 1.25;
export const TAPPED_HIGH = 0.25;

/** The small zone round a spot a tap chose: the clear spots within
 *  `TAPPED_WIDE` figures across and `TAPPED_HIGH` up or down, and the one
 *  nearest the spot as its home. */
export function zoneAround(at: Spot, size: number, layout: Layout, tag: boolean): Zone {
  return zoneAt(at, size, layout, tag, TAPPED_WIDE, TAPPED_HIGH);
}

/** The sizes a figure tries, as shares of the size asked for, where its
 *  corner is too cramped for the full size. */
const SHRINK = [1, 0.85, 0.7] as const;

/** Every seat's zone, so that no two meet: your own first (by your hand),
 *  then the left seat, the top and the right, each kept clear of the spots
 *  of those before it. A figure whose corner has no clear spot stands on
 *  another side of its nameplate (`fallbacks`), and failing that a step
 *  smaller (`Zone.size`). */
export function zonesFor(seats: readonly { pos: SeatPos; size: number; tag: boolean }[], layout: Layout): Record<SeatPos, Zone> {
  const order: readonly SeatPos[] = ["bottom", "left", "top", "right"];
  const out = {} as Record<SeatPos, Zone>;
  let taken: Rect[] = [];
  for (const pos of order) {
    const seat = seats.find((s) => s.pos === pos);
    if (!seat) { out[pos] = { home: null, spots: [] }; continue; }
    const room = { ...layout, obstacles: [...layout.obstacles, ...taken] };
    let zone: Zone = { home: null, spots: [] };
    for (const k of SHRINK) {
      const size = Math.round(seat.size * k);
      for (const at of [ideal(pos, size, room), ...fallbacks(pos, size, room)]) {
        zone = { ...zoneAt(at, size, room, seat.tag), size };
        if (zone.home) break;
      }
      if (zone.home) break;
    }
    out[pos] = zone;
    taken = [...taken, ...zone.spots.map((s) => figureBox(s, zone.size ?? seat.size, seat.tag))];
  }
  return out;
}

/** The clear spot nearest a tap at `p` (where the figure's feet go), on the
 *  felt's safe area, searched out to `reach` px; null when none is clear. */
export function nearestClear(p: Spot, size: number, tag: boolean, layout: Layout, reach = 260): Spot | null {
  const want = { x: Math.round(p.x - size / 2), y: Math.round(p.y - size) };
  const step = Math.max(4, Math.round(size / 6));
  let out: Spot | null = null;
  let best = Infinity;
  for (let dy = -reach; dy <= reach; dy += step) {
    for (let dx = -reach; dx <= reach; dx += step) {
      const d = Math.hypot(dx, dy);
      if (d >= best || d > reach) continue;
      const s = { x: want.x + dx, y: want.y + dy };
      if (clear(s, size, tag, layout)) { best = d; out = s; }
    }
  }
  return out;
}

/** The next spot a walk goes to: a clear one of the zone at least half a
 *  figure from `from`, chosen by `rand` (0 to 1); null when there is none. */
export function nextSpot(zone: Zone, from: Spot, size: number, rand: number): Spot | null {
  const far = zone.spots.filter((s) => Math.hypot(s.x - from.x, s.y - from.y) >= size / 2);
  if (far.length === 0) return null;
  return far[Math.min(far.length - 1, Math.floor(rand * far.length))];
}

/** The clear spot of the zone nearest `s`: where a figure goes when cards
 *  land on it. `upward` counts a step down twice, so of two ways out the
 *  one up is taken. */
export function nearest(zone: Zone, s: Spot, upward = false): Spot | null {
  let out: Spot | null = null;
  let best = Infinity;
  for (const z of zone.spots) {
    const d = Math.hypot(z.x - s.x, z.y - s.y) + (upward && z.y > s.y ? z.y - s.y : 0);
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
