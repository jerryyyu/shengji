import { useEffect, useId, useRef, useState } from "react";
import { lastInputModality, trackInputModality } from "../inputModality";
import { inJoinedRound, leaveCopy } from "./leaveCopy";
import type { LeaveContext } from "./leaveCopy";

trackInputModality();

interface LeaveSheetProps {
  /** Where the leave starts; it picks the title and the one line. */
  context: LeaveContext;
  /** Does the leave (sends leave_room, or leaves the queue's table). */
  onLeave: () => void;
  /** Closes the sheet without leaving: Stay, Escape. */
  onStay: () => void;
}

/** The one confirm every leave goes through: a title, one line of what
 *  leaving costs here, then Stay and Leave. It is a modal dialog, so focus
 *  stays inside it and the page under it is inert; Stay is focused first and
 *  Escape stays. Before a game (the Play table, a room) it rises from the
 *  bottom of a phone; at the table it is a centred card that leaves the
 *  cards in view. Opened from a tap or click, that first focus paints no
 *  ring; the ring returns with the first key pressed inside it. */
export default function LeaveSheet({ context, onLeave, onStay }: LeaveSheetProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const stayRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const lineId = useId();
  // read once: the sheet keeps the line it opened with while it is up
  const [joined] = useState(inJoinedRound);
  const { title, line } = leaveCopy(context, joined);
  const [pointerOpen, setPointerOpen] = useState(() => lastInputModality() === "pointer");
  const place = context.kind === "game" ? "card" : "bottom";

  useEffect(() => {
    const dialog = ref.current!;
    const previous = document.activeElement;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    // Browsers that ignore focusVisible fall back to the data-pointer-open CSS.
    stayRef.current?.focus({ focusVisible: lastInputModality() === "keyboard" });
    return () => {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);

  return (
    <dialog ref={ref} className={`modal-backdrop leave-sheet-backdrop leave-sheet-${place}`} role="alertdialog" aria-modal="true"
            aria-labelledby={titleId} aria-describedby={lineId}
            data-pointer-open={pointerOpen ? "" : undefined}
            onCancel={(e) => { e.preventDefault(); onStay(); }}
            onClick={(e) => { if (e.target === e.currentTarget) onStay(); }}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (pointerOpen) setPointerOpen(false);
              // jsdom and older WebViews send no cancel event for Escape
              if (e.key === "Escape") { e.preventDefault(); onStay(); }
            }}>
      <div className="leave-sheet">
        <div className="leave-sheet-text">
          <h2 id={titleId} className="leave-sheet-title">{title}</h2>
          <p id={lineId} className="leave-sheet-line">{line}</p>
        </div>
        <div className="leave-sheet-actions">
          <button ref={stayRef} type="button" className="leave-sheet-stay" onClick={onStay}>Stay</button>
          <button type="button" className="leave-sheet-leave" onClick={onLeave}>Leave</button>
        </div>
      </div>
    </dialog>
  );
}
