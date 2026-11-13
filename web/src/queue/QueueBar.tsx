import { useRef } from "react";
import { WIDE, openTab } from "../home/route";
import { SHORT_VIEWPORT, useMediaQuery } from "../phoneLayout";
import { BOTS_WARN_MS, clock, partnerName, queue, useNow, useQueue } from "./store";
import type { QueueView } from "./store";
import { useBarClearance } from "./useBarClearance";

interface BarText { label: string; waited: string; sub: string; warn: boolean }

/** What the bar says while you are alone in the queue (2+ people share a
 *  waiting table instead, so there is no count): who is searching and for
 *  how long, then your bot countdown (amber in its last ten seconds). A
 *  pair's other member has no switch, so its line says when it is on. */
function barText(q: QueueView, now: number): BarText {
  const waited = q.since !== null ? clock(now - q.since) : "0:00";
  const botsIn = q.botsAt !== null && !q.waitPlayers ? q.botsAt - now : Infinity;
  const warn = botsIn <= BOTS_WARN_MS;
  const partner = q.partyId ? partnerName(q.party) : null;
  const label = partner ? `You + ${partner}` : q.front && !warn ? "Back in queue" : "Finding a ranked game";
  const sub = q.botsPaused ? "Bots paused"
    : q.waitPlayers ? (q.leader ? "Waiting for people" : "Only tables with people")
    : botsIn <= 0 ? "Adding bots…"
    : botsIn !== Infinity ? `Bots in ${clock(botsIn, true)}`
    : "Waiting for people";
  return { label, waited, sub, warn };
}

function useBar(): { q: QueueView; text: BarText | null } {
  const q = useQueue();
  const shown = q.queued && !q.table;
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
        {q.pending === "bots" ? "Starting…" : "Start with bots"}
      </button>
      {leads ? (
        <button type="button" className="q-cancel" disabled={q.pending !== null} onClick={() => queue.leave()}>
          Leave queue
        </button>
      ) : (
        <span className={`q-cancel q-led${compact ? " compact" : ""}`}>{partner ?? "Partner"} leads</span>
      )}
    </>
  );
}

/** The way back to an open table you waited on: tapping it shows the offer
 *  again. Nothing while none can be joined. */
export function OpenTablesChip({ q }: { q: QueueView }) {
  if (q.openTables <= 0 || q.offer) return null;
  const n = q.openTables;
  return (
    <button type="button" className="q-open-chip" onClick={() => queue.offerShow()}>
      {n === 1 ? "1 open table" : `${n} open tables`}
    </button>
  );
}

/** The leader's switch, "Only tables with people": on, your own timer never
 *  starts a bot game (you can still sit at a table whose timer is someone
 *  else's); off, the bot countdown runs. A pair's other member only sees the
 *  state in the sub-line. The bar puts the switch after its label, the chip
 *  before it. */
export function WaitToggle({ q }: { q: QueueView }) {
  if (!q.leader) return null;
  return (
    <button type="button" role="switch" aria-checked={q.waitPlayers} className="q-wait"
            disabled={q.pending !== null}
            onClick={() => (q.waitPlayers ? queue.allowBots() : queue.waitForPlayers())}>
      <span className="q-wait-label">Only tables with people</span>
      <span className="q-switch" aria-hidden="true" />
    </button>
  );
}

/** The four rows the phone's bar and the wide Play card share: who is
 *  searching and for how long; the countdown; the leader's switch; Start
 *  with bots and Leave queue side by side. */
function CardRows({ q, text, title }: { q: QueueView; text: BarText; title: string }) {
  return (
    <>
      <div className="q-bar-head">
        <span className="q-bar-dot" aria-hidden="true" />
        <b className="q-bar-title">{title}</b>
        <span className="q-bar-time">{text.waited}</span>
      </div>
      <div className="q-bar-subrow">
        <small className="q-bar-sub">{text.sub}</small>
        <OpenTablesChip q={q} />
      </div>
      <WaitToggle q={q} />
      <div className="q-bar-acts"><Actions q={q} /></div>
    </>
  );
}

/** Whether the queue shows inline (an iPad or a desktop window): the Ranked
 *  card on Play and a pill in the top bar elsewhere. A phone held sideways
 *  is wide too, but keeps the strip under its top bar. */
export function useInlineQueue(): boolean {
  const wide = useMediaQuery(WIDE);
  const short = useMediaQuery(SHORT_VIEWPORT);
  return wide && !short;
}

/** A phone's queue bar while you are alone in the queue, pinned above the
 *  tab bar on every tab. Once someone else queues it becomes the waiting
 *  table. */
export default function QueueBar() {
  const { q, text } = useBar();
  const ref = useRef<HTMLDivElement | null>(null);
  useBarClearance(ref, text !== null);
  if (!text) return null;
  return (
    <div ref={ref} className={`q-bar${text.warn ? " warn" : ""}`} role="status" aria-live="polite"
         title={`Waiting ${text.waited}`}>
      <CardRows q={q} text={text} title={text.label} />
    </div>
  );
}

/** The same rows in place of Play's Ranked buttons on an iPad or a desktop
 *  window, titled "Searching" when alone. Null while not searching alone. */
export function QueueCard() {
  const { q, text } = useBar();
  if (!text) return null;
  const title = text.label === "Finding a ranked game" ? "Searching" : text.label;
  return (
    <div className={`q-bar q-card${text.warn ? " warn" : ""}`} role="status" aria-live="polite"
         title={`Waiting ${text.waited}`}>
      <CardRows q={q} text={text} title={title} />
    </div>
  );
}

/** The top bar's way back to the search from another tab on an iPad or a
 *  desktop window: "Searching · 0:24", opening Play. */
export function QueuePill() {
  const { text } = useBar();
  if (!text) return null;
  return (
    <button type="button" className={`q-pill${text.warn ? " warn" : ""}`}
            aria-label={`Searching · ${text.waited}, back to the queue`} onClick={() => openTab("play")}>
      <span className="q-bar-dot" aria-hidden="true" />
      Searching · {text.waited}
    </button>
  );
}

/** The same in one line, for the strip under a sideways phone's top bar. */
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
      <OpenTablesChip q={q} />
      <WaitToggle q={q} />
      <Actions q={q} compact />
    </div>
  );
}

/** The chip on a strip under a sideways phone's top bar. */
export function QueueStrip() {
  const { text } = useBar();
  if (!text) return null;
  return (
    <div className="q-strip">
      <QueueChip />
    </div>
  );
}
