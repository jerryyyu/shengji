// The walking zone by each nameplate never meets the played cards, their
// LEAD / WINS labels, the hand (with room for a chosen card's lift), the
// buttons or the HUD, at phone, tablet and desktop sizes, for the case seen
// on an iPhone (the left seat leading one card on a short hand) and for a
// 2- and a 6-card trick. Your own companion's home is by your own hand, and
// no two seats' zones meet. A tap on the felt finds the nearest clear spot.
import { describe, expect, it } from "vitest";
import { TABLES } from "./seatZones.fixtures";
import type { Measured } from "./seatZones.fixtures";
import { HAND_LIFT, clear, figureBox, meets, nearest, nearestClear, nextSpot, pathClear, zonesFor } from "./seatZones";
import type { Layout, Rect, SeatPos } from "./seatZones";
import { SEAT_SIZE } from "./TableCompanions";
import { companionSize } from "./rig";

// the hand as the table measures it: from its cards' top, raised by a chosen card's lift
const handOf = (m: Measured): Rect => ({ x: m.hand.x, y: m.firstCard.y - HAND_LIFT, w: m.hand.w, h: m.hand.y + m.hand.h - m.firstCard.y + HAND_LIFT });
const layoutOf = (m: Measured, extra: Rect[] = []): Layout => ({
  felt: m.felt, plates: m.plates, tagline: m.tagline, row: m.row, hand: m.firstCard,
  safe: { x0: m.plates.left.x, x1: m.plates.right.x + m.plates.right.w },
  obstacles: [...m.trick, ...m.tags, handOf(m), ...m.buttons, ...m.hud, ...Object.values(m.plates),
              ...(m.tagline ? [m.tagline] : []), ...extra],
});
const POSITIONS: readonly SeatPos[] = ["left", "top", "right", "bottom"];
const sizeOf = (name: string) => (name.startsWith("phone") ? SEAT_SIZE.phone : SEAT_SIZE.tablet);
const seats = (px: number) => POSITIONS.map((pos) => ({ pos, size: px, tag: pos === "bottom" }));

describe("the sizes", () => {
  it("are 44 px at level 2 on a phone, growing to 56; 60 px on a tablet, growing to 76", () => {
    const at = (s: { base: number; max: number }) => [0, 4, 12].map((i) => companionSize(s.base, i, s.max));
    expect(at(SEAT_SIZE.phone)).toEqual([44, 56, 56]);
    expect(at(SEAT_SIZE.tablet)).toEqual([60, 76, 76]);
  });
});

describe("the walking zone", () => {
  for (const [name, m] of Object.entries(TABLES)) {
    for (const px of [sizeOf(name).base, sizeOf(name).max]) {
      it(`${name} at ${px} px: every spot clears the trick, its labels, the hand, the buttons and the HUD`, () => {
        const layout = layoutOf(m);
        const zones = zonesFor(seats(px), layout);
        for (const pos of POSITIONS) {
          const zone = zones[pos];
          expect(zone.home, `${pos} has a home`).not.toBeNull();
          // a cramped corner may have room only to stand
          expect(zone.spots.length, `${pos} has a spot`).toBeGreaterThan(0);
          const drawn = zone.size ?? px;
          // a cramped corner stands its figure a step smaller, never less than 70%
          expect(drawn, pos).toBeGreaterThanOrEqual(Math.round(px * 0.7));
          for (const s of zone.spots) {
            const box = figureBox(s, drawn, pos === "bottom");
            for (const o of [...m.trick, ...m.tags, handOf(m), ...m.buttons, ...m.hud]) {
              expect(meets(box, o), `${pos} ${JSON.stringify(s)} meets ${JSON.stringify(o)}`).toBe(false);
            }
            expect(box.x >= 0 && box.y >= 0 && box.x + box.w <= m.felt.w && box.y + box.h <= m.felt.h).toBe(true);
          }
        }
        // no two seats' figures can meet, wherever each walks in its zone
        for (const a of POSITIONS) for (const b of POSITIONS) {
          if (a >= b) continue;
          for (const s of zones[a].spots) for (const t of zones[b].spots) {
            expect(meets(figureBox(s, zones[a].size ?? px, a === "bottom"), figureBox(t, zones[b].size ?? px, b === "bottom")), `${a} ${b}`).toBe(false);
          }
        }
      });
    }
  }

  it("on a phone your own companion stands by your own hand, not under the left seat's card", () => {
    for (const name of ["phone-land-app-lead1", "phone-land-lead1"]) {
      const m = TABLES[name];
      const px = SEAT_SIZE.phone.base;
      const home = zonesFor(seats(px), layoutOf(m)).bottom.home!;
      // over the left end of the hand, its feet clear of a chosen card's lift
      expect(home.x, name).toBeGreaterThanOrEqual(m.firstCard.x - 8);
      expect(home.x, name).toBeLessThanOrEqual(m.firstCard.x + 3 * px);
      expect(home.y + px, name).toBeLessThanOrEqual(m.firstCard.y - HAND_LIFT);
      expect(home.y + px, name).toBeGreaterThan(m.firstCard.y - HAND_LIFT - px);
      // and nowhere near the left seat's played card and its LEAD label
      for (const o of [...m.trick, ...m.tags]) expect(meets(figureBox(home, px, true), o), name).toBe(false);
    }
  });

  it("the You tag never meets a LEAD label (the overlap seen on an iPhone)", () => {
    const m = TABLES["phone-land-app-lead1"];
    for (const px of [SEAT_SIZE.phone.base, SEAT_SIZE.phone.max]) {
      for (const s of zonesFor(seats(px), layoutOf(m)).bottom.spots) {
        const tag: Rect = { x: s.x, y: s.y - 16, w: px, h: 16 };
        for (const t of m.tags) expect(meets(tag, t)).toBe(false);
      }
    }
  });

  it("a card landing on a spot takes it out of the zone, and the figure goes to the nearest clear one", () => {
    const m = TABLES["phone-land-w2"];
    const px = SEAT_SIZE.phone.max;
    const at = zonesFor(seats(px), layoutOf(m)).left.home!;
    const card: Rect = { x: at.x - 4, y: at.y - 4, w: 30, h: 30 };
    const after = zonesFor(seats(px), layoutOf(m, [card])).left;
    expect(clear(at, px, false, layoutOf(m, [card]))).toBe(false);
    const back = nearest(after, at)!;
    expect(meets(figureBox(back, px, false), card)).toBe(false);
  });

  it("a walk goes at least half a figure, to a spot in the zone", () => {
    const m = TABLES["ipad11-land-w6"];
    const px = SEAT_SIZE.tablet.max;
    const zone = zonesFor(seats(px), layoutOf(m)).right;
    for (const r of [0, 0.3, 0.7, 0.999]) {
      const to = nextSpot(zone, zone.home!, px, r)!;
      expect(Math.hypot(to.x - zone.home!.x, to.y - zone.home!.y)).toBeGreaterThanOrEqual(px / 2);
      expect(zone.spots).toContainEqual(to);
    }
  });

  it("a walk's path is refused where it would cross a card, and allowed round it", () => {
    const m = TABLES["ipad11-land-w2"];
    const px = SEAT_SIZE.tablet.max;
    const zone = zonesFor(seats(px), layoutOf(m)).right;
    const row = zone.spots.filter((s) => s.y === zone.home!.y).sort((p, q) => p.x - q.x);
    const a = row[0];
    const b = row[row.length - 1];
    expect(b.x - a.x).toBeGreaterThanOrEqual(2 * px);
    const card: Rect = { x: (a.x + b.x + px) / 2 - 3, y: a.y, w: 6, h: px };
    const blocked = layoutOf(m, [card]);
    expect(clear(a, px, false, blocked) && clear(b, px, false, blocked)).toBe(true);
    expect(pathClear(a, b, px, false, blocked)).toBe(false);
    expect(pathClear(a, b, px, false, layoutOf(m))).toBe(true);
  });
});

describe("a tap on the felt", () => {
  it("finds the clear spot nearest the tap, inside the safe area, clear of everything", () => {
    for (const name of ["phone-land-app-lead1", "ipad11-land-w2", "desktop-w6"]) {
      const m = TABLES[name];
      const px = sizeOf(name).base;
      const layout = layoutOf(m);
      // a tap in the open felt below the top seat: the figure's feet land there
      const open = { x: m.felt.w / 2 - 60, y: m.trick[0].y + m.trick[0].h + 40 };
      const s = nearestClear(open, px, true, layout)!;
      expect(clear(s, px, true, layout), name).toBe(true);
      expect(s.x, name).toBeGreaterThanOrEqual(layout.safe!.x0);
      expect(s.x + px, name).toBeLessThanOrEqual(layout.safe!.x1);
      // a tap on a played card lands beside it, never on it
      const card = m.trick[0];
      const t = nearestClear({ x: card.x + card.w / 2, y: card.y + card.h / 2 }, px, true, layout)!;
      expect(meets(figureBox(t, px, true), card), name).toBe(false);
      expect(Math.hypot(t.x + px / 2 - (card.x + card.w / 2), t.y + px - (card.y + card.h / 2)), name).toBeLessThan(card.w + card.h + 2 * px);
    }
  });
});
