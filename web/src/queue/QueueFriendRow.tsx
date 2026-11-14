import { useAuth } from "../auth";
import { queue } from "./store";

/** Me's row that opens the pair sheet. */
export default function QueueFriendRow() {
  const account = useAuth();
  if (account.status !== "in") return null;
  return (
    <ul className="grp">
      <li>
        <button type="button" className="grp-row q-me-row" onClick={() => queue.openParty()}>
          <span className="grp-label">Queue with a friend</span><span className="grp-value chev" />
        </button>
      </li>
    </ul>
  );
}
