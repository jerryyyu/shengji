import { useState } from "react";
import ConfirmSheet from "./ConfirmSheet";
import { inJoinedRound, leaveCopy } from "./leaveCopy";
import type { LeaveContext } from "./leaveCopy";

interface LeaveSheetProps {
  /** Where the leave starts; it picks the title and the one line. */
  context: LeaveContext;
  /** Does the leave (sends table_leave, or leaves the queue's table). */
  onLeave: () => void;
  /** Closes the sheet without leaving: Stay, Escape. */
  onStay: () => void;
  /** The question in place of the context's own, e.g. a link to another table. */
  title?: string;
}

/** The confirm every leave goes through: the one confirm sheet with the
 *  leave's copy, a title and one line of what leaving costs here (none when
 *  it costs nothing), then Stay and Leave. Before a game (the Play table, a
 *  room) it rises from the bottom of a phone; at the table it is a centred
 *  card that leaves the cards in view. */
export default function LeaveSheet({ context, onLeave, onStay, title: ask }: LeaveSheetProps) {
  // read once: the sheet keeps the line it opened with while it is up
  const [joined] = useState(inJoinedRound);
  const copy = leaveCopy(context, joined);
  return (
    <ConfirmSheet title={ask ?? copy.title} line={copy.line} cancel="Stay" confirm="Leave" danger
                  place={context.kind === "game" ? "card" : "bottom"} onConfirm={onLeave} onCancel={onStay} />
  );
}
