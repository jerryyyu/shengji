import { pickHandLine } from "../handLineParts";
import type { HandLineParts } from "../handLineParts";

/** Exactly one text line above your hand, or none. A preceding sibling of
 *  `.hand`, so an idle coach cue pulses the lit cards with it. `tap` remounts
 *  the line for each refused tap, so the same reason fades in again. */
export default function HandLine({ parts, tap = 0, nudge = false }: { parts: HandLineParts; tap?: number; nudge?: boolean }) {
  const line = pickHandLine(parts);
  if (line === null) return null;
  const cls = line.kind === "reason" ? "" : line.kind === "help" ? " help" : ` coach${nudge ? " nudge" : ""}`;
  return (
    <div className={`hand-line${cls}`} role="status" key={line.kind === "reason" ? `r${tap}` : line.kind}>
      {line.text}
    </div>
  );
}
