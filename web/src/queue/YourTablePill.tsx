import { useContext } from "react";
import { TimerRing } from "../components/MoveClock";
import { openTab } from "../home/route";
import { BOTS_WARN_MS, BOT_FILL_MS, sharedTable, useNow, useQueue } from "./store";
import type { QueueView } from "./store";
import { SeatedAtContext } from "./seatedAt";
import type { SeatedAt } from "./seatedAt";
import { t, useT } from "../i18n";

interface PillText { label: string; left: number | null; warn: boolean }

/** The bots' fill time while it runs at your table or in your search; null
 *  when no clock runs (waiting for people, a table without a bot timer, or
 *  a search held on another device). */
function botsAt(q: QueueView): number | null {
  if (q.elsewhere) return null;
  const at = q.frame?.timers.bots?.at ?? null;
  return sharedTable(q.frame) || !q.waitPlayers ? at : null;
}

function pillText(at: SeatedAt, q: QueueView, now: number): PillText | null {
  if (at === "game") return { label: t("home.pillGame"), left: null, warn: false };
  if (!q.queued) return null;
  const fill = botsAt(q);
  const left = fill === null ? null : Math.max(0, fill - now);
  return { label: t("home.pillTable"), left, warn: left !== null && left <= BOTS_WARN_MS };
}

/** The one way back to your table or game from another tab, on phone and
 *  desktop alike: a dot, "Your table" (or "Your game"), and the bots' ring
 *  while it runs, amber in its last ten seconds. A tap opens Play, which
 *  holds the panel or the game. Nothing shows when you sit nowhere. */
export default function YourTablePill() {
  useT();
  const at = useContext(SeatedAtContext);
  const q = useQueue();
  const now = useNow(at === null && q.queued, 250);
  const text = pillText(at, q, now);
  if (!text) return null;
  return (
    <button type="button" className={`table-pill${text.warn ? " warn" : ""}`}
            aria-label={t("home.pillAria", { name: text.label })} onClick={() => openTab("play")}>
      <span className="table-pill-dot" aria-hidden="true" />
      <span className="table-pill-label">{text.label}</span>
      {text.left !== null ? <TimerRing left={text.left / 1000} total={BOT_FILL_MS / 1000} /> : null}
    </button>
  );
}
