import { useEffect, useRef, useState } from "react";
import { conn } from "../ws";

interface LeaveButtonProps {
  /** "hud" is the small pill in the top bar; "dialog" is a full-size secondary
   *  button for modal screens, which make the HUD unreachable. */
  variant?: "hud" | "dialog";
}

/** Leave control with a confirm step. The top-bar pill arms on the first tap
 * ("Leave game?") and sends leave_room on a second tap within 3s; the dialog
 * button opens a Stay / Leave choice that waits. */
export default function LeaveButton({ variant = "hud" }: LeaveButtonProps) {
  const [armed, setArmed] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    []
  );

  const click = () => {
    if (!armed) {
      setArmed(true);
      timer.current = window.setTimeout(() => {
        timer.current = null;
        setArmed(false);
      }, 3000);
    } else {
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = null;
      setArmed(false);
      conn.send({ type: "leave_room" });
    }
  };

  if (variant === "dialog") {
    // In a dialog Leave asks and waits: no timer, so a slow second tap never
    // re-arms it instead of leaving.
    if (confirming) {
      return (
        <div className="dialog-leave-confirm" role="group" aria-label="Leave game?">
          <span className="dialog-leave-q">Leave game?</span>
          <button type="button" className="btn subtle" onClick={() => setConfirming(false)}>Stay</button>
          <button type="button" className="btn subtle danger" onClick={() => conn.send({ type: "leave_room" })}>
            Leave
          </button>
        </div>
      );
    }
    return (
      <button
        type="button"
        className="btn subtle danger dialog-leave-btn"
        onClick={() => setConfirming(true)}
        title="Leave the game (a bot takes over your seat)"
      >
        Leave game
      </button>
    );
  }

  return (
    <button
      className={`leave-btn${armed ? " armed" : ""}`}
      onClick={click}
      title="Leave the game (a bot takes over your seat)"
    >
      {armed ? "Leave game?" : "Leave"}
    </button>
  );
}
