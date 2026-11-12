import { BOTS_WARN_MS, clock, partnerName, queue, useNow, useQueue } from "./store";
import type { QueueView } from "./store";

interface BarText { title: string; sub: string; warn: boolean }

/** What the bar says: the wait and the count, "bots in 0:05" near the bot
 *  fill, or "Back in queue" after someone else missed a ready check. */
function barText(q: QueueView, now: number): BarText {
  const waited = q.since !== null ? clock(now - q.since) : "0:00";
  const botsIn = q.botsAt !== null ? q.botsAt - now : Infinity;
  const warn = botsIn <= BOTS_WARN_MS;
  const partner = q.partyId ? partnerName(q.party) : null;
  if (q.front && !warn) return { title: "Back in queue", sub: "you keep your place", warn };
  const tail = warn ? (botsIn > 0 ? `bots in ${clock(botsIn, true)}` : "adding bots…") : `${q.count} in queue`;
  if (partner) return { title: `You + ${partner} · ${waited}`, sub: tail, warn };
  return { title: "Finding a game", sub: `${waited} · ${tail}`, warn };
}

function useBar(): { q: QueueView; text: BarText | null } {
  const q = useQueue();
  const shown = q.queued && !q.check;
  const now = useNow(shown, 250);
  return { q, text: shown ? barText(q, now) : null };
}

function Actions({ q, compact }: { q: QueueView; compact?: boolean }) {
  const leads = q.leader;
  const partner = q.partyId ? partnerName(q.party) : null;
  return (
    <>
      <button type="button" className="q-bots" disabled={!leads || q.pending !== null}
              title={leads ? undefined : `${partner ?? "Your partner"} leads`}
              onClick={() => queue.startBots()}>
        {q.pending === "bots" ? "Starting…" : "Play with bots now"}
      </button>
      {leads ? (
        <button type="button" className="q-cancel" disabled={q.pending !== null} onClick={() => queue.leave()}>
          Cancel
        </button>
      ) : (
        <span className={`q-cancel q-led${compact ? " compact" : ""}`}>{partner ?? "Partner"} leads</span>
      )}
    </>
  );
}

/** A phone's queue bar, pinned above the tab bar on every tab. */
export default function QueueBar() {
  const { q, text } = useBar();
  if (!text) return null;
  return (
    <div className={`q-bar${text.warn ? " warn" : ""}`} role="status" aria-live="polite">
      <span className="q-spin" aria-hidden="true" />
      <span className="q-bar-text">
        <b>{text.title}</b>
        <small>{text.sub}</small>
      </span>
      <Actions q={q} />
    </div>
  );
}

/** The same, as a chip in the wide layout's top bar. */
export function QueueChip() {
  const { q, text } = useBar();
  if (!text) return null;
  return (
    <div className={`q-chip${text.warn ? " warn" : ""}`} role="status" aria-live="polite">
      <span className="q-spin" aria-hidden="true" />
      <span className="q-chip-text"><span className="q-chip-title">{text.title} · </span>{text.sub}</span>
      <Actions q={q} compact />
    </div>
  );
}
