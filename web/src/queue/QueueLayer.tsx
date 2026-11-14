import { useEffect, useRef } from "react";
import { clearToast, currentToast, showToast } from "../toast";
import { useQueue } from "./store";

/** The queue's notices, said as the app's one toast. The table itself is a
 *  panel on Play (TablePanel). */
export default function QueueLayer() {
  const note = useQueue().note;
  const shown = useRef<number | null>(null);
  useEffect(() => {
    if (note) {
      shown.current = showToast(note.title, { info: true, sub: note.sub }).id;
      return;
    }
    // a note the queue took back (signed out, reset) goes with it
    if (shown.current !== null && currentToast()?.id === shown.current) clearToast();
    shown.current = null;
    // each note has its own id, so the same words twice are said twice
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [note?.id]);
  return null;
}
