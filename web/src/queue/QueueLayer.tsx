import { useEffect } from "react";
import type { ConnStatus } from "../ws";
import { PartySheet, SoloSheet } from "./PartySheet";
import { queue, useQueue } from "./store";
import OpenTableOffer from "./OpenTableOffer";
import WaitingTable from "./WaitingTable";

/** Read a `?party=CODE` invite link once and drop it from the address. */
function takeInviteCode(): string | null {
  const params = new URLSearchParams(window.location.search);
  const code = params.get("party");
  if (!code) return null;
  params.delete("party");
  const rest = params.toString();
  window.history.replaceState(window.history.state, "", `${window.location.pathname}${rest ? `?${rest}` : ""}${window.location.hash}`);
  return code;
}

/** Everything of the queue that floats over any screen: the waiting table,
 *  an open-table offer, the Solo / With a friend and pair sheets, and the
 *  queue's notices. */
export default function QueueLayer({ status }: { status: ConnStatus }) {
  const q = useQueue();
  useEffect(() => {
    const code = takeInviteCode();
    if (code) {
      queue.setJoinCode(code);
      queue.findAfterSignIn = true;
    }
  }, []);
  // An invite link opens the pair sheet with its code once the socket is up,
  // for guests and accounts alike.
  useEffect(() => {
    if (!queue.findAfterSignIn || status !== "open") return;
    queue.findAfterSignIn = false;
    queue.openSheet(queue.view.joinCode ? "party" : "solo");
  }, [status]);

  return (
    <>
      {q.sheet === "solo" ? <SoloSheet /> : null}
      {q.sheet === "party" ? <PartySheet /> : null}
      <WaitingTable />
      <OpenTableOffer />
      {q.note ? (
        <div key={q.note.id} className="q-toast" role="status">
          <span className="q-toast-i" aria-hidden="true">!</span>
          <span>{q.note.title}{q.note.sub ? <small>{q.note.sub}</small> : null}</span>
        </div>
      ) : null}
    </>
  );
}
