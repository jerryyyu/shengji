import { useRef } from "react";
import type { ReactNode } from "react";
import { TimerRing } from "../components/MoveClock";
import { WIDE, openTab } from "../home/route";
import { SHORT_VIEWPORT, useMediaQuery } from "../phoneLayout";
import { BOTS_WARN_MS, BOT_FILL_MS, useNow, useQueue } from "./store";
import type { QueueView } from "./store";
import { stripLabel } from "./tableText";
import { useBarClearance } from "./useBarClearance";

interface StripText { label: string; time: ReactNode; warn: boolean }

/** The way back to the table from another tab: what it is and the bots'
 *  countdown as a ring, or Join while a table with a seat is offered. Amber
 *  in the last ten seconds before bots fill it. A table with no bot timer
 *  shows no clock. */
function stripText(q: QueueView, now: number): StripText {
  const label = stripLabel(q);
  if (label === "Table with a seat") return { label, time: "Join", warn: false };
  const at = q.elsewhere ? null : q.table ? q.table.timer?.at ?? null : q.waitPlayers ? null : q.botsAt;
  const warn = at !== null && at - now <= BOTS_WARN_MS;
  const time = at === null ? null
    : <TimerRing left={Math.max(0, at - now) / 1000} total={BOT_FILL_MS / 1000} />;
  return { label, time, warn };
}

function useStrip(): StripText | null {
  const q = useQueue();
  const now = useNow(q.queued, 250);
  return q.queued ? stripText(q, now) : null;
}

/** Whether the queue shows inline (an iPad or a desktop window): the panel
 *  in the Ranked card's place on Play and a pill in the top bar elsewhere.
 *  A phone held sideways is wide too, but keeps the strip under its top bar. */
export function useInlineQueue(): boolean {
  const wide = useMediaQuery(WIDE);
  const short = useMediaQuery(SHORT_VIEWPORT);
  return wide && !short;
}

/** A phone's strip above the tab bar on a tab other than Play while you are
 *  at a table: one tap goes back to the panel on Play. */
export default function QueueBar() {
  const text = useStrip();
  const ref = useRef<HTMLDivElement | null>(null);
  useBarClearance(ref, text !== null);
  if (!text) return null;
  return (
    <div ref={ref} className={`q-bar${text.warn ? " warn" : ""}`}>
      <button type="button" className="q-bar-go" aria-label={`${text.label}, back to Play`}
              onClick={() => openTab("play")}>
        <span className="q-bar-dot" aria-hidden="true" />
        <b className="q-bar-title">{text.label}</b>
        {text.time !== null ? <span className="q-bar-time" aria-hidden="true">{text.time}</span> : null}
      </button>
    </div>
  );
}

/** The top bar's way back to the table from another tab on an iPad or a
 *  desktop window: "Your table" and the bots' ring; a narrow top bar keeps
 *  only the dot and the ring. */
export function QueuePill() {
  const text = useStrip();
  if (!text) return null;
  return (
    <button type="button" className={`q-pill${text.warn ? " warn" : ""}`}
            aria-label={`${text.label}, back to Play`} onClick={() => openTab("play")}>
      <span className="q-bar-dot" aria-hidden="true" />
      <span className="q-pill-label">{text.label}</span>
      {text.time}
    </button>
  );
}

/** The same on a strip under a sideways phone's top bar. */
export function QueueStrip() {
  const text = useStrip();
  if (!text) return null;
  return (
    <div className="q-strip">
      <button type="button" className={`q-chip${text.warn ? " warn" : ""}`}
              aria-label={`${text.label}, back to Play`} onClick={() => openTab("play")}>
        <span className="q-bar-dot" aria-hidden="true" />
        <span className="q-chip-text">{text.label}</span>
        {text.time}
      </button>
    </div>
  );
}
