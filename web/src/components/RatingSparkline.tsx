import { useState } from "react";
import type { KeyboardEvent, PointerEvent, ReactNode } from "react";
import { isZh, t as tr, useT } from "../i18n";

/** The rating after each recent round, drawn as one gold line over a faint
 *  fill with the latest point marked. At rest it has no axis and no visible
 *  text: its accessible name says what it shows. Pressing and dragging
 *  across it (or the arrow keys, once focused) moves a guide and the dot to
 *  one round, and one readout above it gives that round's rating, its change
 *  and its date; letting go puts it back at rest. Fewer than two points draw
 *  nothing. */
export function sparkPath(history: readonly number[], w: number, h: number, pad = 6): {
  line: string; last: [number, number]; pts: [number, number][];
} {
  const lo = Math.min(...history);
  const hi = Math.max(...history);
  const span = hi - lo || 1;
  const pts = history.map((v, i): [number, number] => [
    (i / (history.length - 1)) * w,
    hi === lo ? h / 2 : h - pad - ((v - lo) / span) * (h - 2 * pad),
  ]);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  return { line, last: pts[pts.length - 1], pts };
}

/** The point nearest a horizontal fraction of the chart's width. */
export function pointAt(frac: number, n: number): number {
  return Math.round(Math.min(1, Math.max(0, frac)) * (n - 1));
}

/** A round's date, short and in the app's language; a round today says so. */
export function shortDate(at: number, now: Date = new Date()): string {
  const d = new Date(at * 1000);
  if (d.toDateString() === now.toDateString()) return tr("home.today");
  const sameYear = d.getFullYear() === now.getFullYear();
  return new Intl.DateTimeFormat(isZh() ? "zh-Hans" : "en-US", {
    month: "short", day: "numeric", ...(sameYear ? {} : { year: "numeric" }),
  }).format(d);
}

const W = 300;
const H = 56;

export default function RatingSparkline({ history, at }: { history: readonly number[]; at?: readonly number[] }) {
  const t = useT();
  const [active, setActive] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  if (history.length < 2) return null;
  const n = history.length;
  const { line, last, pts } = sparkPath(history, W, H);
  const first = Math.round(history[0]);
  const now = Math.round(history[n - 1]);
  // the history is the rating before the first round, then one value after
  // each round: n values span n - 1 rounds
  const rounds = n - 1;
  const label = t("me.spark", { n: rounds, from: first.toLocaleString("en-US"), to: now.toLocaleString("en-US") });

  const fromPointer = (e: PointerEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    return pointAt(box.width ? (e.clientX - box.left) / box.width : 1, n);
  };
  const down = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setDragging(true);
    setActive(fromPointer(e));
  };
  const move = (e: PointerEvent<HTMLDivElement>) => {
    if (dragging) setActive(fromPointer(e));
  };
  const release = () => {
    setDragging(false);
    setActive(null);
  };
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    const cur = active ?? n - 1;
    let next: number | null;
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") next = Math.max(0, cur - 1);
    else if (e.key === "ArrowRight" || e.key === "ArrowUp") next = Math.min(n - 1, cur + 1);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = n - 1;
    else if (e.key === "Escape") next = null;
    else return;
    e.preventDefault();
    setActive(next);
  };

  const shown = active ?? n - 1;
  const [px, py] = active === null ? last : pts[shown];
  const xPct = (px / W) * 100;
  let readout: ReactNode = null;
  if (active !== null) {
    const value = Math.round(history[active]);
    const change = active > 0 ? value - Math.round(history[active - 1]) : null;
    const when = at && at.length === n ? shortDate(at[active]) : null;
    readout = (
      <span className="me-spark-chip" style={{ left: `${xPct}%`, transform: `translateX(-${xPct}%)` }}>
        <b>{value.toLocaleString("en-US")}</b>
        {change === null ? null : " "}
        {change === null ? null : (
          <span className={change > 0 ? "delta-up" : change < 0 ? "delta-dn" : "delta-flat"}>
            {change > 0 ? `▲${change}` : change < 0 ? `▼${-change}` : "±0"}
          </span>
        )}
        {when ? " · " : null}
        {when ? <span className="me-spark-when">{when}</span> : null}
      </span>
    );
  }
  return (
    <>
      {/* the one readout, there only while a round is picked; announced
          politely as it changes, outside the chart so its name stays */}
      <div className="me-spark-read" aria-live="polite">{readout}</div>
      <div className={`me-spark${active === null ? "" : " scrubbing"}`} role="img" aria-label={label} tabIndex={0}
           onPointerDown={down} onPointerMove={move} onPointerUp={release} onPointerCancel={release}
           onLostPointerCapture={release} onKeyDown={key} onBlur={() => setActive(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
          <path className="me-spark-fill" d={`${line} L${W} ${H} L0 ${H} Z`} />
          <path className="me-spark-line" d={line} />
        </svg>
        {active === null ? null : <span className="me-spark-guide" aria-hidden="true" style={{ left: `${xPct}%` }} />}
        {/* the latest point, or the picked one, drawn outside the stretched
            SVG so it stays round */}
        <span className="me-spark-dot" aria-hidden="true"
              style={{ left: `${xPct}%`, top: `${(py / H) * 100}%` }} />
      </div>
    </>
  );
}
