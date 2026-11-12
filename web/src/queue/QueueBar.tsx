import { useLayoutEffect, useRef } from "react";
import type { RefObject } from "react";
import { BOTS_WARN_MS, clock, partnerName, queue, useNow, useQueue } from "./store";
import type { QueueView } from "./store";

interface BarText { label: string; waited: string; sub: string; warn: boolean }

/** What the bar says: who is searching and for how long, then the bot fill
 *  countdown (amber in its last ten seconds), with the queue count. A pair's
 *  other member has no switch, so its line says when the entry waits for
 *  real players. */
function barText(q: QueueView, now: number): BarText {
  const waited = q.since !== null ? clock(now - q.since) : "0:00";
  const botsIn = q.botsAt !== null && !q.waitPlayers ? q.botsAt - now : Infinity;
  const warn = botsIn <= BOTS_WARN_MS;
  const partner = q.partyId ? partnerName(q.party) : null;
  const label = partner ? `You + ${partner}` : q.front && !warn ? "Back in queue" : "Finding a ranked game";
  const count = `${q.count} in queue`;
  const sub = q.waitPlayers ? (q.leader ? count : `Real players only · ${count}`)
    : botsIn <= 0 ? "Adding bots…"
    : botsIn !== Infinity ? `Bots in ${clock(botsIn, true)} · ${count}`
    : count;
  return { label, waited, sub, warn };
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
        {q.pending === "bots" ? "Starting…" : "Play bots"}
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

/** The leader's switch: on, the entry waits for real players and no bots
 *  join; off, the bot countdown runs. A pair's other member only sees the
 *  state in the sub-line. The bar puts the switch after its label, the chip
 *  before it. */
function WaitToggle({ q }: { q: QueueView }) {
  if (!q.leader) return null;
  return (
    <button type="button" role="switch" aria-checked={q.waitPlayers} className="q-wait"
            disabled={q.pending !== null}
            onClick={() => (q.waitPlayers ? queue.allowBots() : queue.waitForPlayers())}>
      <span className="q-wait-label">Wait for real players</span>
      <span className="q-switch" aria-hidden="true" />
    </button>
  );
}

/** While the bar shows, `--q-bar-clear` on the root is the distance from
 *  the viewport's bottom to just above the bar, so notices can sit over it
 *  instead of on it. */
function useBarClearance(bar: RefObject<HTMLDivElement | null>, shown: boolean) {
  useLayoutEffect(() => {
    const node = bar.current;
    if (!shown || !node) return;
    const root = document.documentElement;
    const set = () => {
      const clear = Math.round(window.innerHeight - node.getBoundingClientRect().top + 8);
      root.style.setProperty("--q-bar-clear", `${clear}px`);
    };
    set();
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(set);
    ro?.observe(node);
    window.addEventListener("resize", set);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", set);
      root.style.removeProperty("--q-bar-clear");
    };
  }, [bar, shown]);
}

/** A phone's queue bar, pinned above the tab bar on every tab, in four
 *  rows: who is searching and for how long; the countdown and queue count;
 *  the leader's wait switch; Play bots and Cancel side by side. */
export default function QueueBar() {
  const { q, text } = useBar();
  const ref = useRef<HTMLDivElement | null>(null);
  useBarClearance(ref, text !== null);
  if (!text) return null;
  return (
    <div ref={ref} className={`q-bar${text.warn ? " warn" : ""}`} role="status" aria-live="polite"
         title={`Waiting ${text.waited}`}>
      <div className="q-bar-head">
        <span className="q-bar-dot" aria-hidden="true" />
        <b className="q-bar-title">{text.label}</b>
        <span className="q-bar-time">{text.waited}</span>
      </div>
      <small className="q-bar-sub">{text.sub}</small>
      <WaitToggle q={q} />
      <div className="q-bar-acts"><Actions q={q} /></div>
    </div>
  );
}

/** The same, as a chip in the wide layout's top bar. */
export function QueueChip() {
  const { q, text } = useBar();
  if (!text) return null;
  return (
    <div className={`q-chip${text.warn ? " warn" : ""}`} role="status" aria-live="polite"
         title={`Waiting ${text.waited}`}>
      <span className="q-spin" aria-hidden="true" />
      <span className="q-chip-text">
        <span className="q-chip-title">{text.label} · {text.waited} · </span>{text.sub}
      </span>
      <WaitToggle q={q} />
      <Actions q={q} compact />
    </div>
  );
}

/** The chip's content on a strip under the top bar, for wide windows too
 *  narrow to fit it beside four tabs (CSS shows one or the other). */
export function QueueStrip() {
  const { text } = useBar();
  if (!text) return null;
  return (
    <div className="q-strip">
      <QueueChip />
    </div>
  );
}
