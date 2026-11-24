/** The rating after each recent round, drawn as one gold line over a faint
 *  fill with the latest point marked. No axis and no visible text: its
 *  accessible name says what it shows. Fewer than two points draw nothing. */
export function sparkPath(history: readonly number[], w: number, h: number, pad = 6): { line: string; last: [number, number] } {
  const lo = Math.min(...history);
  const hi = Math.max(...history);
  const span = hi - lo || 1;
  const pts = history.map((v, i): [number, number] => [
    (i / (history.length - 1)) * w,
    hi === lo ? h / 2 : h - pad - ((v - lo) / span) * (h - 2 * pad),
  ]);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  return { line, last: pts[pts.length - 1] };
}

const W = 300;
const H = 56;

export default function RatingSparkline({ history }: { history: readonly number[] }) {
  if (history.length < 2) return null;
  const { line, last } = sparkPath(history, W, H);
  const first = Math.round(history[0]);
  const now = Math.round(history[history.length - 1]);
  const label = `Rating over your last ${history.length} rounds, from ${first.toLocaleString("en-US")} to ${now.toLocaleString("en-US")}`;
  return (
    <div className="me-spark" role="img" aria-label={label}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
        <path className="me-spark-fill" d={`${line} L${W} ${H} L0 ${H} Z`} />
        <path className="me-spark-line" d={line} />
      </svg>
      {/* the latest point, drawn outside the stretched SVG so it stays round */}
      <span className="me-spark-dot" aria-hidden="true"
            style={{ left: `${(last[0] / W) * 100}%`, top: `${(last[1] / H) * 100}%` }} />
    </div>
  );
}
