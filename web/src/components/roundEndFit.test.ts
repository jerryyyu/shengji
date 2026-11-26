import { describe, expect, it } from "vitest";
import { FIT, fitDetails, rowWidth } from "./roundEndFit";

// The Details row's content width on the round-end card, measured in a
// browser: a phone held upright (390 × 844, the table turned sideways) and
// sideways (844 × 390) both draw the 440px phone card; a desktop (1280 × 800)
// draws the 480px card. The narrowest is a 300px card.
const VIEWPORTS = { phonePortrait390: 406, phoneLandscape844: 406, desktop1280: 414, card300: 266 };
const COUNTS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];

describe("the round-end Details row fits its width for every card count", () => {
  for (const [name, width] of Object.entries(VIEWPORTS)) {
    it(`${name}: 1 to 12 cards a seat, with the 8-card kitty, stays inside ${width}px`, () => {
      for (const perSeat of COUNTS) {
        const fit = fitDetails({ width, kitty: 8, seats: 4, perSeat });
        expect(fit.total).toBeLessThanOrEqual(width + 1e-6);
        expect(rowWidth({ width, kitty: 8, seats: 4, perSeat }, fit.cw, fit.step)).toBeCloseTo(fit.total);
        expect(fit.cw).toBeGreaterThanOrEqual(FIT.minCw);
        expect(fit.cw).toBeLessThanOrEqual(FIT.cw);
        expect(fit.step).toBeLessThanOrEqual(FIT.step);
        expect(fit.step).toBeGreaterThan(0);
      }
    });
  }

  it("a sweep of widths, kitty sizes, seat counts and cards a seat never overflows, and shrinks in order", () => {
    for (let width = 280; width <= 1200; width += 7) {
      for (const kitty of [0, 6, 8, 12]) {
        for (const seats of [0, 4, 5, 6]) {
          for (let perSeat = 1; perSeat <= 12; perSeat++) {
            const input = { width, kitty, seats, perSeat };
            const fit = fitDetails(input);
            expect(fit.total, JSON.stringify(input)).toBeLessThanOrEqual(width + 1e-6);
            // the card shrinks only once the step is at its readable minimum,
            // and the step goes under it only at the smallest card
            if (fit.cw < FIT.cw) expect(fit.step, JSON.stringify(input)).toBeLessThanOrEqual(FIT.minStep + 1e-9);
            if (fit.step < FIT.minStep - 1e-9 && fit.step < FIT.step) {
              expect(fit.cw === FIT.cw || fit.cw === FIT.minCw, JSON.stringify(input)).toBe(true);
            }
            // a fit at rest is never squeezed for nothing
            if (rowWidth(input, FIT.cw, FIT.step) <= width) expect(fit).toMatchObject({ cw: FIT.cw, step: FIT.step });
          }
        }
      }
    }
  });

  it("uses the width it has: the step is the widest that fits, not a fixed table per count", () => {
    const a = fitDetails({ width: 326, kitty: 8, seats: 4, perSeat: 4 });
    const b = fitDetails({ width: 360, kitty: 8, seats: 4, perSeat: 4 });
    expect(b.step).toBeGreaterThan(a.step);
    expect(a.total).toBeCloseTo(326);
  });

  it("the cards at rest before the width is known", () => {
    expect(fitDetails({ width: 0, kitty: 8, seats: 4, perSeat: 8 })).toMatchObject({ cw: FIT.cw, step: FIT.step });
  });
});
