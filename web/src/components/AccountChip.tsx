import { useEffect, useState } from "react";
import { effectiveName } from "../auth";
import type { AuthUser } from "../auth";
import { fetchStats } from "../ratings/api";
import { Avatar } from "../home/HomeShell";
import { openTab } from "../home/route";

/** The signed-in player's chip: avatar, the name they play under and their
 *  rating once it has loaded. One button that opens Me, where the name is
 *  edited. It sits on Play on a phone and at the top bar's end when wide. */
export default function AccountChip({ user }: { user: AuthUser }) {
  const [rating, setRating] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    fetchStats().then((r) => { if (live) setRating(r.ok ? r.data.rating : null); });
    return () => { live = false; };
  }, [user]);
  const name = effectiveName(user) || user.email;
  return (
    <button type="button" className="account-pill" onClick={() => openTab("me", "stats")}
            aria-label={`${name}${rating !== null ? `, rating ${rating}` : ""}, open profile`}>
      <Avatar user={user} />
      <span className="account-pill-name">{name}</span>
      {rating !== null ? <span className="account-pill-rating">{rating.toLocaleString("en-US")}</span> : null}
    </button>
  );
}
