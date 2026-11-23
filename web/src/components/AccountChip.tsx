import { useEffect, useState } from "react";
import { effectiveName, isUnlinkedDevice } from "../auth";
import { guestName } from "../guestName";
import type { AuthUser } from "../auth";
import { fetchStats } from "../ratings/api";
import { Avatar } from "../home/HomeShell";
import { openTab } from "../home/route";

/** The signed-in player's chip: avatar, the name they play under and their
 *  rating once it has loaded. One button that opens Me, where the name is
 *  edited. It sits on Play on a phone and at the top bar's end when wide.
 *  The app's own account, with no Apple or Google sign-in yet, keeps the
 *  guest chip's pencil and opens the identity sheet, where it signs in;
 *  `compact` (the wide top bar) has no pencil. */
export default function AccountChip({ user, compact = false }: { user: AuthUser; compact?: boolean }) {
  const [rating, setRating] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    fetchStats().then((r) => { if (live) setRating(r.ok ? r.data.rating : null); });
    return () => { live = false; };
  }, [user]);
  const name = effectiveName(user) || user.email;
  const device = isUnlinkedDevice(user);
  const ratingText = rating !== null ? `, rating ${rating}` : "";
  return (
    <button type="button" className={`account-pill${device ? " device-pill" : ""}`}
            onClick={device ? () => guestName.open() : () => openTab("me", "stats")}
            aria-label={`${name}${ratingText}, ${device ? "edit name" : "open profile"}`}>
      <Avatar user={user} />
      <span className="account-pill-name">{name}</span>
      {rating !== null ? <span className="account-pill-rating">{rating.toLocaleString("en-US")}</span> : null}
      {device && !compact ? <span className="guest-pill-edit" aria-hidden="true">✎</span> : null}
    </button>
  );
}
