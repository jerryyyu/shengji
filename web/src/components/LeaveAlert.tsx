import { useEffect, useId, useRef, useState } from "react";
import { conn } from "../ws";
import { lastInputModality, trackInputModality } from "../inputModality";

trackInputModality();

/** The two lines a leave alert shows: a ranked game warns about the result
 *  of the round in play, but between rounds that result is already recorded
 *  and the next round has not started, so leaving costs nothing; a practice
 *  game on this device simply ends; any other game plays on with a bot in
 *  your seat. */
export function leaveCopy(ranked: boolean, practice = false,
                          betweenRounds = false): { title: string; body: string } {
  if (practice) return { title: "Leave this game?", body: "This practice game ends." };
  if (ranked && betweenRounds) return { title: "Leave the table?", body: "This round's result is kept." };
  return ranked
    ? { title: "Leave this ranked game?", body: "A bot takes your seat, and this round counts as at best a draw." }
    : { title: "Leave this game?", body: "A bot takes your seat and the others keep playing." };
}

interface LeaveAlertProps {
  ranked: boolean;
  /** Offline practice: the game ends (the start screen then sends the player home). */
  practice?: boolean;
  /** Opened from the round-end screen: the round is over and rated. */
  betweenRounds?: boolean;
  /** Closes the alert without leaving: Keep playing, Escape. */
  onKeep: () => void;
  /** Runs after leave_room is sent, for the caller to tidy up. */
  onLeft?: () => void;
}

/** A centred alert that asks before leaving the game. It is a modal dialog,
 *  so focus stays inside it and the table under it is inert; Keep playing is
 *  focused first, and Escape keeps playing. Leave sends leave_room. Opened
 *  from a tap or click, that first focus paints no ring; the ring returns
 *  with the first key pressed inside the alert. */
export default function LeaveAlert({ ranked, practice = false, betweenRounds = false, onKeep, onLeft }: LeaveAlertProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const bodyId = useId();
  const { title, body } = leaveCopy(ranked, practice, betweenRounds);
  const [pointerOpen, setPointerOpen] = useState(() => lastInputModality() === "pointer");

  useEffect(() => {
    const dialog = ref.current!;
    const previous = document.activeElement;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    // Browsers that ignore focusVisible fall back to the data-pointer-open CSS.
    keepRef.current?.focus({ focusVisible: lastInputModality() === "keyboard" });
    return () => {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);

  const leave = () => {
    conn.send({ type: "leave_room" });
    onLeft?.();
  };

  return (
    <dialog ref={ref} className="modal-backdrop leave-alert-backdrop" role="alertdialog"
            aria-labelledby={titleId} aria-describedby={bodyId}
            data-pointer-open={pointerOpen ? "" : undefined}
            onCancel={(e) => { e.preventDefault(); onKeep(); }}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (pointerOpen) setPointerOpen(false);
              // jsdom and older WebViews send no cancel event for Escape
              if (e.key === "Escape") { e.preventDefault(); onKeep(); }
            }}>
      <div className="leave-alert">
        <div className="leave-alert-text">
          <h2 id={titleId} className="leave-alert-title">{title}</h2>
          <p id={bodyId} className="leave-alert-body">{body}</p>
        </div>
        <div className="leave-alert-actions">
          <button ref={keepRef} type="button" className="leave-alert-keep" onClick={onKeep}>Keep playing</button>
          <button type="button" className="leave-alert-leave" onClick={leave}>Leave</button>
        </div>
      </div>
    </dialog>
  );
}
