import { useState } from "react";
import LeaveAlert from "./LeaveAlert";
import { OFFLINE } from "../offlineMode";

interface LeaveButtonProps {
  /** "hud" is the small pill in the top bar; "dialog" is a full-size secondary
   *  button for modal screens, which make the HUD unreachable. */
  variant?: "hud" | "dialog";
  /** A matched game: the alert says what leaving does to the result. */
  ranked?: boolean;
  /** Offline practice; defaults to the page's mode. */
  practice?: boolean;
}

/** Leave control: a tap opens the leave alert, which waits for Keep playing
 *  or Leave. */
export default function LeaveButton({ variant = "hud", ranked = false, practice = OFFLINE }: LeaveButtonProps) {
  const [asking, setAsking] = useState(false);
  const alert = asking ? <LeaveAlert ranked={ranked} practice={practice} onKeep={() => setAsking(false)} onLeft={() => setAsking(false)} /> : null;

  if (variant === "dialog") {
    return (
      <>
        <button
          type="button"
          className="btn subtle danger dialog-leave-btn"
          onClick={() => setAsking(true)}
          title="Leave the game (a bot takes your seat)"
        >
          Leave game
        </button>
        {alert}
      </>
    );
  }

  return (
    <>
      <button className="leave-btn" onClick={() => setAsking(true)} title="Leave the game (a bot takes your seat)">
        Leave
      </button>
      {alert}
    </>
  );
}
