/** Shared motion tokens and helpers. The durations and easings mirror the
 *  `--dur-*` and `--ease-*` custom properties in index.css (a test keeps the
 *  two in step), so CSS transitions and Web Animations feel like one system.
 *
 *  Every helper is visual only: it never delays, reorders or gates a state
 *  update. Under `prefers-reduced-motion: reduce`, or where the Web
 *  Animations API is missing, each helper does nothing and the UI shows the
 *  final state at once. */

export const DUR = {
  fast: 120,
  lift: 400,
  flight: 340,
  reflow: 280,
  sweep: 400,
  count: 500,
  pulse: 900,
} as const;

export const EASE = {
  /** Fast start, long settle: flights and reflow. */
  outExpo: "cubic-bezier(0.16, 1, 0.3, 1)",
  /** Slight overshoot: lifts and chip pops. */
  back: "cubic-bezier(0.34, 1.56, 0.64, 1)",
  /** Symmetric: the sweep that gathers a finished trick. */
  inOut: "cubic-bezier(0.65, 0, 0.35, 1)",
} as const;

export function prefersReducedMotion(): boolean {
  try {
    return typeof window !== "undefined"
      && typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/** True when an element can be animated and the viewer has not asked for
 *  reduced motion. */
export function canAnimate(el: Element | null | undefined): el is HTMLElement {
  return !!el && typeof (el as HTMLElement).animate === "function" && !prefersReducedMotion();
}

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface Delta {
  dx: number;
  dy: number;
}

/** FLIP "invert" step: the offset that puts `last`'s center on `first`'s. */
export function centerDelta(first: Box, last: Box): Delta {
  return {
    dx: first.left + first.width / 2 - (last.left + last.width / 2),
    dy: first.top + first.height / 2 - (last.top + last.height / 2),
  };
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

/** Union of boxes, or null for none. */
export function unionBox(boxes: Box[]): Box | null {
  if (boxes.length === 0) return null;
  let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity;
  for (const x of boxes) {
    l = Math.min(l, x.left);
    t = Math.min(t, x.top);
    r = Math.max(r, x.left + x.width);
    b = Math.max(b, x.top + x.height);
  }
  return { left: l, top: t, width: r - l, height: b - t };
}

/** Keyframes for a card flight from offset `from` back to its resting place
 *  along a quadratic arc that bows upward, with a rotation that settles to 0
 *  and a scale that starts at `scale`. The arc is sampled so the effect-level
 *  easing moves the card along the curve rather than a straight line. */
export function flightKeyframes(from: Delta, rotateDeg: number, scale: number, samples = 6): Keyframe[] {
  const dist = Math.hypot(from.dx, from.dy);
  const lift = Math.min(60, dist * 0.18);
  // Unit normal to the path, chosen to point up the screen (or right when the
  // path is vertical) so every arc bows the same readable way.
  let nx = dist ? -from.dy / dist : 0;
  let ny = dist ? from.dx / dist : 0;
  if (ny > 0 || (Math.abs(ny) < 1e-6 && nx < 0)) { nx = -nx; ny = -ny; }
  const cx = from.dx / 2 + nx * lift;
  const cy = from.dy / 2 + ny * lift;
  const frames: Keyframe[] = [];
  for (let i = 0; i <= samples; i++) {
    const t = i / samples;
    const u = 1 - t;
    const x = u * u * from.dx + 2 * u * t * cx;
    const y = u * u * from.dy + 2 * u * t * cy;
    const r = rotateDeg * u;
    const s = scale + (1 - scale) * t;
    frames.push({
      offset: t,
      transform: `translate(${round(x)}px, ${round(y)}px) rotate(${round(r)}deg) scale(${round(s)})`,
    });
  }
  frames[frames.length - 1].transform = "none";
  return frames;
}

/** Keyframes that gather one finished-trick play onto the winner's play and
 *  carry the pile toward the winner's seat as it fades. */
export function sweepKeyframes(toWinner: Delta, toSeat: Delta): Keyframe[] {
  return [
    { offset: 0, transform: "none", opacity: 1 },
    { offset: 0.45, transform: `translate(${round(toWinner.dx)}px, ${round(toWinner.dy)}px) scale(0.96)`, opacity: 1 },
    { offset: 1, transform: `translate(${round(toSeat.dx)}px, ${round(toSeat.dy)}px) scale(0.6)`, opacity: 0 },
  ];
}

function round(v: number): number {
  return Math.round(v * 100) / 100;
}

/** Current translation of an element's running transform animation, read
 *  from its computed matrix; lets a new FLIP start from where the card is
 *  drawn rather than jumping. */
export function currentTranslate(el: Element): Delta {
  try {
    const m = getComputedStyle(el).transform;
    if (!m || m === "none") return { dx: 0, dy: 0 };
    const nums = m.slice(m.indexOf("(") + 1, -1).split(",").map(Number);
    if (m.startsWith("matrix3d(")) return { dx: nums[12] || 0, dy: nums[13] || 0 };
    return { dx: nums[4] || 0, dy: nums[5] || 0 };
  } catch {
    return { dx: 0, dy: 0 };
  }
}

/** Ease-out cubic, the count-up's curve. */
export function easeOutCubic(t: number): number {
  const u = 1 - clamp(t, 0, 1);
  return 1 - u * u * u;
}

export interface TweenClock {
  now: () => number;
  request: (cb: (t: number) => void) => number;
  cancel: (id: number) => void;
}

const defaultClock: TweenClock = {
  now: () => (typeof performance !== "undefined" ? performance.now() : Date.now()),
  request: (cb) => (typeof requestAnimationFrame === "function"
    ? requestAnimationFrame(cb)
    : (setTimeout(() => cb(Date.now()), 16) as unknown as number)),
  cancel: (id) => (typeof cancelAnimationFrame === "function"
    ? cancelAnimationFrame(id)
    : clearTimeout(id)),
};

/** Tween a number from `from` to `to`. `onUpdate` always receives exactly `to`
 *  last, so a tween can never leave a display short of its value. Returns a
 *  cancel function; cancelling stops further updates (the caller decides
 *  what to show next). A zero duration updates once, synchronously. */
export function tweenNumber(
  from: number,
  to: number,
  duration: number,
  onUpdate: (v: number) => void,
  clock: TweenClock = defaultClock,
): () => void {
  if (duration <= 0 || from === to) {
    onUpdate(to);
    return () => {};
  }
  const start = clock.now();
  let id: number | null = null;
  let done = false;
  const step = () => {
    if (done) return;
    const t = (clock.now() - start) / duration;
    if (t >= 1) {
      done = true;
      onUpdate(to);
      return;
    }
    onUpdate(from + (to - from) * easeOutCubic(t));
    id = clock.request(step);
  };
  id = clock.request(step);
  return () => {
    done = true;
    if (id !== null) clock.cancel(id);
  };
}
