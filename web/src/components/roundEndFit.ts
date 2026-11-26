/** The round-end Details row: the kitty's fan, then one fan per seat of the
 *  last trick, all on one line inside the card's width. Every fan shares one
 *  card width and one overlap step, solved from the measured width and the
 *  actual counts: the step shrinks first (down to the step that still shows
 *  each card's rank), then the card, and only at the smallest card does the
 *  step go tighter. The row never wraps and never runs past `width`. */

export const FIT = {
  /** the card's width at rest, and its overlap step */
  cw: 34,
  step: 18,
  /** the step that still shows a card's rank and suit in its corner */
  minStep: 11,
  /** the smallest card; below it only the step tightens */
  minCw: 22,
  /** the tightest step at the smallest card (the cards then nearly stack) */
  floorStep: 1,
  /** between seats, and between the kitty and the trick */
  seatGap: 6,
  groupGap: 12,
  /** a seat's column is never narrower than this, so its name still reads */
  colMin: 40,
} as const;

export interface FitInput {
  /** the row's content width in px */
  width: number;
  /** cards in the kitty (0 when it is not shown) */
  kitty: number;
  /** seats in the last trick (0 when there is none) */
  seats: number;
  /** cards each seat played; every seat plays the same count */
  perSeat: number;
}

export interface Fit {
  cw: number;
  step: number;
  /** one seat's column: its fan, or colMin when the fan is narrower */
  col: number;
  kittyWidth: number;
  /** the row's width at this fit, gaps included */
  total: number;
}

const fan = (m: number, cw: number, step: number) => (m > 0 ? cw + (m - 1) * step : 0);

function gaps({ kitty, seats, perSeat }: FitInput): number {
  const trick = seats > 0 && perSeat > 0;
  return (trick ? (seats - 1) * FIT.seatGap : 0) + (trick && kitty > 0 ? FIT.groupGap : 0);
}

/** A seat's narrowest column: room for its name, unless the width cannot
 *  hold that many seats beside the kitty's tightest fan. */
function colMinOf({ width, kitty, seats, perSeat }: FitInput): number {
  if (!(width > 0) || seats === 0 || perSeat === 0) return FIT.colMin;
  const room = (width - gaps({ width, kitty, seats, perSeat }) - fan(kitty, FIT.minCw, FIT.floorStep)) / seats;
  return Math.min(FIT.colMin, Math.max(FIT.minCw, room));
}

export function rowWidth(input: FitInput, cw: number, step: number): number {
  const trick = input.seats > 0 && input.perSeat > 0;
  const col = trick ? Math.max(fan(input.perSeat, cw, step), colMinOf(input)) : 0;
  return fan(input.kitty, cw, step) + (trick ? input.seats * col : 0) + gaps(input);
}

/** The largest step at card width `cw` that fits the row in `width`:
 *  (width − gaps − the cards' own widths) / (the overlapped slots). When
 *  that leaves a seat's fan under colMin, the seats are held at colMin and
 *  only the kitty's slots share what is left (or nothing fits, -Infinity). */
function stepAt(input: FitInput, cw: number): number {
  const { width, kitty, seats, perSeat } = input;
  const trick = seats > 0 && perSeat > 0;
  const kSlots = Math.max(0, kitty - 1);
  const sSlots = trick ? seats * (perSeat - 1) : 0;
  const cards = (kitty > 0 ? cw : 0) + (trick ? seats * cw : 0);
  const step = kSlots + sSlots > 0 ? (width - gaps(input) - cards) / (kSlots + sSlots) : Infinity;
  if (!trick || fan(perSeat, cw, step) >= colMinOf(input)) return step;
  const rest = width - gaps(input) - seats * colMinOf(input) - (kitty > 0 ? cw : 0);
  return kSlots > 0 ? rest / kSlots : rest >= 0 ? Infinity : -Infinity;
}

/** The largest card width at step `step` that fits the row in `width`, by
 *  the same two cases. */
function cwAt(input: FitInput, step: number): number {
  const { width, kitty, seats, perSeat } = input;
  const trick = seats > 0 && perSeat > 0;
  const slots = Math.max(0, kitty - 1) + (trick ? seats * (perSeat - 1) : 0);
  const fans = (kitty > 0 ? 1 : 0) + (trick ? seats : 0);
  if (fans === 0) return FIT.cw;
  const cw = (width - gaps(input) - slots * step) / fans;
  if (!trick || fan(perSeat, cw, step) >= colMinOf(input)) return cw;
  return kitty > 0 ? width - gaps(input) - seats * colMinOf(input) - (kitty - 1) * step : -Infinity;
}

export function fitDetails(input: FitInput): Fit {
  const make = (cw: number, step: number): Fit => {
    const trick = input.seats > 0 && input.perSeat > 0;
    return {
      cw, step,
      col: trick ? Math.max(fan(input.perSeat, cw, step), colMinOf(input)) : 0,
      kittyWidth: fan(input.kitty, cw, step),
      total: rowWidth(input, cw, step),
    };
  };
  // no width yet (the first render, or a test's DOM): the cards at rest
  if (!(input.width > 0)) return make(FIT.cw, FIT.step);
  const step = Math.min(FIT.step, stepAt(input, FIT.cw));
  if (step >= FIT.minStep) return make(FIT.cw, step);
  const cw = Math.min(FIT.cw, cwAt(input, FIT.minStep));
  if (cw >= FIT.minCw) return make(cw, FIT.minStep);
  return make(FIT.minCw, Math.max(FIT.floorStep, Math.min(FIT.minStep, stepAt(input, FIT.minCw))));
}
