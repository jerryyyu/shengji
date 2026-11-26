// The walking zone by each nameplate never meets the played cards, the
// hand, the buttons or the HUD, at phone, tablet and desktop sizes, for a
// two-card and a six-card trick, and it gives way when cards land on a spot.
import { describe, expect, it } from "vitest";
import { TABLES } from "./seatZones.fixtures";
import type { Measured } from "./seatZones.fixtures";
import { clear, figureBox, meets, nearest, nextSpot, zoneFor } from "./seatZones";
import type { Layout, Rect, SeatPos } from "./seatZones";
import { SEAT_SIZE } from "./TableCompanions";

const layoutOf = (m: Measured, extra: Rect[] = []): Layout => ({
  felt: m.felt, plates: m.plates, tagline: m.tagline, row: m.row,
  obstacles: [...m.trick, m.hand, ...m.buttons, ...m.hud, ...Object.values(m.plates), ...(m.tagline ? [m.tagline] : []), ...extra],
});
const POSITIONS: readonly SeatPos[] = ["left", "top", "right", "bottom"];

describe("the walking zone", () => {
  for (const [name, m] of Object.entries(TABLES)) {
    const size = name.startsWith("phone") ? SEAT_SIZE.phone.max : SEAT_SIZE.tablet.max;
    it(`${name}: every spot clears the trick, the hand, the buttons and the HUD`, () => {
      const layout = layoutOf(m);
      for (const pos of POSITIONS) {
        const zone = zoneFor(pos, size, layout);
        expect(zone.home, `${pos} has a home`).not.toBeNull();
        expect(zone.spots.length, `${pos} has room to walk`).toBeGreaterThan(4);
        for (const s of zone.spots) {
          const box = figureBox(s, size, pos === "bottom");
          for (const o of [...m.trick, m.hand, ...m.buttons, ...m.hud]) expect(meets(box, o), `${pos} ${JSON.stringify(s)}`).toBe(false);
          expect(box.x >= 0 && box.y >= 0 && box.x + box.w <= m.felt.w && box.y + box.h <= m.felt.h).toBe(true);
        }
      }
    });
  }

  it("a card landing on a spot takes it out of the zone, and the figure goes to the nearest clear one", () => {
    const m = TABLES["phone-land-w2"];
    const size = SEAT_SIZE.phone.max;
    const before = zoneFor("left", size, layoutOf(m));
    const at = before.home!;
    const card: Rect = { x: at.x - 4, y: at.y - 4, w: 30, h: 30 };
    const after = zoneFor("left", size, layoutOf(m, [card]));
    expect(clear(at, size, false, layoutOf(m, [card]))).toBe(false);
    const back = nearest(after, at)!;
    expect(meets(figureBox(back, size, false), card)).toBe(false);
  });

  it("a walk goes at least half a figure, to a spot in the zone", () => {
    const m = TABLES["ipad11-land-w6"];
    const size = SEAT_SIZE.tablet.max;
    const zone = zoneFor("right", size, layoutOf(m));
    for (const r of [0, 0.3, 0.7, 0.999]) {
      const to = nextSpot(zone, zone.home!, size, r)!;
      expect(Math.hypot(to.x - zone.home!.x, to.y - zone.home!.y)).toBeGreaterThanOrEqual(size / 2);
      expect(zone.spots).toContainEqual(to);
    }
  });
});

describe("a walk's path", () => {
  it("is refused where it would cross a card, and allowed round it", async () => {
    const { pathClear } = await import("./seatZones");
    const m = TABLES["ipad11-land-w2"];
    const size = SEAT_SIZE.tablet.max;
    const layout = layoutOf(m);
    const a = { x: 10, y: 640 - 59 - 120 };
    const card = { x: 120, y: a.y - 10, w: 60, h: 80 };
    const blocked = layoutOf(m, [card]);
    const b = { x: 220, y: a.y };
    expect(clear(a, size, false, blocked) && clear(b, size, false, blocked)).toBe(true);
    expect(pathClear(a, b, size, false, blocked)).toBe(false);
    expect(pathClear(a, { x: a.x + 30, y: a.y }, size, false, layout)).toBe(true);
  });
});
