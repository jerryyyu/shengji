import { useEffect, useId, useRef } from "react";
import { conn } from "../ws";

/** The two lines a leave alert shows: a ranked game warns about the result,
 *  a practice game on this device simply ends, any other game plays on with
 *  a bot in your seat. */
export function leaveCopy(ranked: boolean, practice = false): { title: string; body: string } {
  if (practice) return { title: "Leave this game?", body: "This practice game ends." };
  return ranked
    ? { title: "Leave this ranked game?", body: "A bot takes your seat, and this round counts as at best a draw." }
    : { title: "Leave this game?", body: "A bot takes your seat and the others keep playing." };
}

interface LeaveAlertProps {
  ranked: boolean;
  /** Offline practice: the game ends (the start screen then sends the player home). */
  practice?: boolean;
  /** Closes the alert without leaving: Keep playing, Escape. */
  onKeep: () => void;
  /** Runs after leave_room is sent, for the caller to tidy up. */
  onLeft?: () => void;
}

/** A centred alert that asks before leaving the game. It is a modal dialog,
 *  so focus stays inside it and the table under it is inert; Keep playing is
 *  focused first, and Escape keeps playing. Leave sends leave_room. */
export default function LeaveAlert({ ranked, practice = false, onKeep, onLeft }: LeaveAlertProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const bodyId = useId();
  const { title, body } = leaveCopy(ranked, practice);

  useEffect(() => {
    const dialog = ref.current!;
    const previous = document.activeElement;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    keepRef.current?.focus();
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
            onCancel={(e) => { e.preventDefault(); onKeep(); }}
            onKeyDown={(e) => {
              e.stopPropagation();
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
