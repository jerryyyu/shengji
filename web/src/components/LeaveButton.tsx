import { useEffect, useRef, useState } from "react";
import { conn } from "../ws";

interface LeaveButtonProps {
  /** "hud" is the small pill in the top bar; "dialog" is a full-size secondary
   *  button for modal screens, which make the HUD unreachable. */
  variant?: "hud" | "dialog";
}

/** Leave control with a confirm step: first tap arms ("Leave game?"),
 * second tap within 3s sends leave_room; otherwise it reverts. */
export default function LeaveButton({ variant = "hud" }: LeaveButtonProps) {
  const [armed, setArmed] = useState(false);
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
    return (
      <button
        type="button"
        className={`btn subtle danger dialog-leave-btn${armed ? " armed" : ""}`}
        onClick={click}
        title="Leave the game (a bot takes over your seat)"
      >
        {armed ? "Tap again to leave" : "Leave game"}
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
