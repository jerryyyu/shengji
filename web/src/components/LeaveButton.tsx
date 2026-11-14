import { useState } from "react";
import LeaveAlert from "./LeaveAlert";
import { OFFLINE } from "../offlineMode";

interface LeaveButtonProps {
  /** A matched game: the alert says what leaving does to the result. */
  ranked?: boolean;
  /** Offline practice; defaults to the page's mode. */
  practice?: boolean;
}

/** The HUD's Leave control: a tap opens the leave alert, which waits for Keep
 *  playing or Leave. The round-end screen has its own Leave beside Next round. */
export default function LeaveButton({ ranked = false, practice = OFFLINE }: LeaveButtonProps) {
  const [asking, setAsking] = useState(false);
  return (
    <>
      <button className="leave-btn" onClick={() => setAsking(true)} title="Leave the game (a bot takes your seat)">
        Leave
      </button>
      {asking ? <LeaveAlert ranked={ranked} practice={practice} onKeep={() => setAsking(false)} onLeft={() => setAsking(false)} /> : null}
    </>
  );
}
