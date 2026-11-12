import { useEffect, useState } from "react";
import type { AuthUser } from "../auth";
import { deltaText, fetchStats } from "../ratings/api";
import type { MyStats } from "../ratings/api";
import { Avatar } from "../home/HomeShell";
import { openTab } from "../home/route";

/** The signed-in player's rating chip under the lobby's title: avatar,
 *  rating and this week's change; a tap opens the Leaderboard tab. Until
 *  the stats arrive (or when they cannot load) it is left out. */
export default function AccountChip({ user }: { user: AuthUser }) {
  const [stats, setStats] = useState<MyStats | null>(null);
  useEffect(() => {
    let live = true;
    fetchStats().then((r) => { if (live) setStats(r.ok ? r.data : null); });
    return () => { live = false; };
  }, [user]);
  if (!stats) return null;
  const d = stats.week_delta;
  return (
    <button type="button" className="rating-chip" onClick={() => openTab("leaderboard")}
            aria-label={`Rating ${stats.rating}, ${deltaText(d)} this week: open the leaderboard`}>
      <Avatar user={user} />
      <span className="rating-chip-value">{stats.rating}</span>
      <span className={d > 0 ? "delta-up" : d < 0 ? "delta-dn" : "delta-flat"}>{deltaText(d)}</span>
      <span className="rating-chip-chev" aria-hidden="true">›</span>
    </button>
  );
}
