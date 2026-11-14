import { useState } from "react";
import LeaveSheet from "./LeaveSheet";
import { conn } from "../ws";
import { OFFLINE } from "../offlineMode";

interface LeaveButtonProps {
  /** A ranked table: the sheet says what leaving does to the result. */
  ranked?: boolean;
  /** A guest seat: never rated, so the sheet speaks of no ranking. */
  guest?: boolean;
  /** Offline practice; defaults to the page's mode. */
  practice?: boolean;
}

/** The HUD's Leave control: a tap opens the leave sheet, which waits for Stay
 *  or Leave. The round-end screen has its own Leave beside Next round. */
export default function LeaveButton({ ranked = false, guest = false, practice = OFFLINE }: LeaveButtonProps) {
  const [asking, setAsking] = useState(false);
  return (
    <>
      <button className="leave-btn" onClick={() => setAsking(true)} title="Leave the game (a bot takes your seat)">
        Leave
      </button>
      {asking ? (
        <LeaveSheet context={{ kind: "game", ranked, guest, practice }}
                    onStay={() => setAsking(false)}
                    onLeave={() => { conn.send({ type: "leave_room" }); setAsking(false); }} />
      ) : null}
    </>
  );
}
