import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { ConnStatus } from "../ws";
import { conn } from "../ws";
import { offlineGame, offlineOffered } from "./offlineGame";
import { lastInputModality } from "../inputModality";
import { trapTab } from "../queue/Sheet";
import { isStalled, subscribeStalled } from "../link";

/** A short blip reconnects on its own; Retry joins the pill only after this. */
export const RETRY_AFTER_MS = 10_000;
/** Long enough that a tunnel or a lift does not trigger the full screen. */
export const LOST_AFTER_MS = 60_000;

export type ConnPhase = "open" | "waiting" | "retry" | "lost";

/** How long the socket has been short of "open", as a phase, and a retry
 *  that reconnects at once and starts the wait over. The socket's own
 *  backoff keeps reconnecting underneath; this only decides what is shown. */
function useConnPhase(status: ConnStatus): [ConnPhase, () => void] {
  // an action the server has not answered reads as a drop at once, while
  // the socket is still being proven dead
  const [stalled, setStalledView] = useState(isStalled);
  useEffect(() => subscribeStalled(setStalledView), []);
  const open = status === "open" && !stalled;
  const [phase, setPhase] = useState<ConnPhase>(open ? "open" : "waiting");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (open) { setPhase("open"); return; }
    setPhase("waiting");
    const retry = window.setTimeout(() => setPhase("retry"), RETRY_AFTER_MS);
    const lost = window.setTimeout(() => setPhase("lost"), LOST_AFTER_MS);
    return () => { window.clearTimeout(retry); window.clearTimeout(lost); };
  }, [open, attempt]);
  const retry = useCallback(() => {
    setAttempt((n) => n + 1);
    conn.reconnect();
  }, []);
  return [open ? "open" : phase, retry];
}

interface Props {
  status: ConnStatus;
  /** In a room or a game: the pill sits below the table's header. */
  inRoom: boolean;
  /** A game in progress, which a bot plays on while this device is away. */
  inGame: boolean;
  /** Whether the pill shows while the socket is down. Play with no table
   *  says it on its presence line instead; the full screen shows anyway. */
  pill?: boolean;
  /** A nearby table is over for this joiner: the full screen says so, with
   *  Leave in place of Retry. */
  ended?: { title: string; onLeave: () => void } | null;
}

/** The one connection surface, in the lobby and at the table alike: a pill
 *  while the socket is down, with Retry after RETRY_AFTER_MS, and one full
 *  screen after LOST_AFTER_MS. While the socket is open the table may show
 *  SeatHeldPill in the same place; this shows nothing. */
export default function ConnectionPill({ status, inRoom, inGame, pill = true, ended = null }: Props) {
  const [phase, retry] = useConnPhase(status);
  if (ended) return <ConnectionLost inGame={false} onRetry={ended.onLeave} ended={ended.title} />;
  if (phase === "open") return null;
  if (phase === "lost") return <ConnectionLost inGame={inGame} onRetry={retry} />;
  if (!pill) return null;
  // the first connect of a page load is not a drop: no socket has opened yet
  const label = conn.generation > 0 ? "Reconnecting…" : "Connecting…";
  return (
    <div className={`reconnect-banner${inRoom ? "" : " at-home"}${phase === "retry" ? " with-retry" : ""}`}
         role="status">
      <span className="conn-dot" />
      <span className="reconnect-text">{label}</span>
      {phase === "retry" ? (
        <button type="button" className="reconnect-retry" onClick={retry}>Retry</button>
      ) : null}
    </div>
  );
}

/** The connection pill's other state, in the same place: the socket is
 *  open and a bot plays your seat until you are back. */
export function SeatHeldPill({ onBack }: { onBack: () => void }) {
  return (
    <div className="reconnect-banner seat-held with-retry" role="status">
      <span className="conn-dot" />
      <span className="reconnect-text">A bot holds your seat</span>
      <button type="button" className="reconnect-retry" onClick={onBack}>I’m back</button>
    </div>
  );
}

/** Makes every element outside `keep` inert, up to the body, other modal
 *  layers included: nothing behind this screen can take focus or a tap.
 *  Returns the undo. */
function inertAllOutside(keep: HTMLElement): () => void {
  const made: HTMLElement[] = [];
  for (let n: HTMLElement | null = keep; n && n !== document.body; n = n.parentElement) {
    const parent: HTMLElement | null = n.parentElement;
    if (!parent) break;
    for (const sib of Array.from(parent.children)) {
      if (sib === n || !(sib instanceof HTMLElement) || sib.hasAttribute("inert")) continue;
      sib.setAttribute("inert", "");
      made.push(sib);
    }
  }
  return () => { for (const el of made) el.removeAttribute("inert"); };
}

const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled]):not([type='hidden']), "
  + "select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

/** Where focus goes when the screen closes: the control that had it, or
 *  else the first control on the page, since that control may be gone. */
function restoreFocus(previous: Element | null): void {
  if (previous instanceof HTMLElement && previous.isConnected && previous !== document.body
      && !previous.closest("[inert]")) {
    previous.focus({ preventScroll: true });
    return;
  }
  const first = Array.from(document.querySelectorAll<HTMLElement>(`.app ${FOCUSABLE}`))
    .find((el) => !el.closest("[inert], [hidden], [aria-hidden='true'], .conn-lost"));
  first?.focus({ preventScroll: true });
}

/** The one full-screen state: a modal dialog over everything, sheets and
 *  alerts included. Retry has focus, Tab stays inside, the page behind is
 *  inert, and Escape does not dismiss it, since only a connection or Retry
 *  ends it. On closing, focus goes back to where it was. */
function ConnectionLost({ inGame, onRetry, ended = null }: { inGame: boolean; onRetry: () => void; ended?: string | null }) {
  const ref = useRef<HTMLDialogElement>(null);
  const retryRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const bodyId = useId();
  useEffect(() => {
    const dialog = ref.current!;
    const previous = document.activeElement;
    // opened last, it sits in the top layer above any dialog already open
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    const undoInert = inertAllOutside(dialog);
    retryRef.current?.focus({ focusVisible: lastInputModality() === "keyboard" });
    return () => {
      undoInert();
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      restoreFocus(previous);
    };
  }, []);
  return (
    <dialog ref={ref} className="conn-lost" role="alertdialog" aria-modal="true"
            aria-labelledby={titleId} aria-describedby={inGame ? bodyId : undefined}
            onCancel={(e) => e.preventDefault()}
            onKeyDown={(e) => {
              // a sheet underneath listens on the document for Tab and Escape
              e.stopPropagation();
              if (e.key === "Escape") e.preventDefault();
              trapTab(e.nativeEvent, ref.current!);
            }}>
      <div className="conn-lost-mark" aria-hidden="true">!</div>
      <h1 className="conn-lost-title" id={titleId}>{ended ?? "No connection"}</h1>
      {inGame ? <p className="conn-lost-body" id={bodyId}>A bot holds your seat.</p> : null}
      <button ref={retryRef} type="button" className="btn gold conn-lost-retry" onClick={onRetry}>{ended ? "Leave" : "Retry"}</button>
      {offlineOffered() && !ended ? (
        <button type="button" className="btn conn-lost-bots" onClick={() => offlineGame.startFromPlay()}>
          Play offline with the bots
        </button>
      ) : null}
    </dialog>
  );
}
