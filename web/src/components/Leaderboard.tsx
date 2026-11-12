import { useState } from "react";
import { useAuth } from "../auth";
import { deltaText, fetchLeaderboard } from "../ratings/api";
import type { Leaderboard as Board, LeaderRow, Loaded, Period } from "../ratings/api";
import { Segmented } from "../home/HomeShell";
import { tabMemory, useCachedResource, useTabScroll, viewerScope } from "../home/session";
import { WIDE } from "../home/route";
import LargeTitlePage from "../home/LargeTitlePage";
import { useMediaQuery } from "../phoneLayout";
import GoogleSignIn, { SignInUnavailable } from "./GoogleSignIn";
import { SkeletonRows } from "./GamesList";

const PERIODS = [
  { value: "week", label: "This week" },
  { value: "all", label: "All time" },
] as const;

/** A rating as read aloud: 1,042, with the thousands separator. */
export function ratingText(rating: number): string {
  return rating.toLocaleString("en-US");
}

/** This week's change; no change is a dash, not a zero. */
function weekDeltaText(delta: number): string {
  return delta === 0 ? "–" : deltaText(delta);
}

function deltaClass(delta: number): string {
  return delta > 0 ? "delta-up" : delta < 0 ? "delta-dn" : "delta-flat";
}

export function Row({ row }: { row: LeaderRow }) {
  const top = row.rank !== null && row.rank <= 3;
  return (
    <li className={`lb-row${row.you ? " me" : ""}`}>
      <span className={`lb-rank${top ? " top" : ""}`}>{row.rank ?? "—"}</span>
      <span className="avatar avatar-sm" aria-hidden="true">{row.name.slice(0, 1).toUpperCase()}</span>
      <span className="lb-name">
        <span className="lb-name-text">{row.you ? `${row.name} (you)` : row.name}</span>
        {row.provisional ? <span className="lb-new" title="Fewer than 20 ranked rounds">new</span> : null}
      </span>
      <span className="lb-rating">{ratingText(row.rating)}</span>
      <span className={`lb-delta ${deltaClass(row.week_delta)}`} title="Change this week">
        {weekDeltaText(row.week_delta)}
      </span>
    </li>
  );
}

/** The bot anchor: a divider at its rating, not a competitor with a rank. */
function Anchor({ name, rating }: { name: string; rating: number }) {
  return <li className="lb-row anchor"><span className="lb-anchor-text">{name} · {ratingText(rating)}</span></li>;
}

/** The top players with the bot anchor placed where its rating falls. */
function Rows({ board }: { board: Board }) {
  const { players, anchor } = board;
  const at = players.findIndex((p) => p.rating < anchor.rating);
  const split = at === -1 ? players.length : at;
  return (
    <ul className="grp lb-list">
      {players.slice(0, split).map((p, i) => <Row key={`a${i}`} row={p} />)}
      <Anchor {...anchor} />
      {players.slice(split).map((p, i) => <Row key={`b${i}`} row={p} />)}
    </ul>
  );
}

/** Under the board for a guest: what signing in buys, and the button.
 *  This is the one place ranked and unranked play are explained; the other
 *  sign-in prompts link here. */
function SignInToRank({ clientId }: { clientId: string }) {
  return (
    <div className="signin-card compact lb-rated">
      <h3>Sign in to be ranked</h3>
      <p>Ranked rounds move your rating here, starting from 1000.</p>
      <GoogleSignIn clientId={clientId} />
    </div>
  );
}

/** The Leaderboard tab: ranked players by rating, this week or all time.
 *  Guests read it too; the viewer's own row (or, for a guest, a sign-in
 *  card) is pinned to the bottom when it is not among the rows shown.
 *  This week on the first visit; after that the period last chosen, with
 *  the last board shown at once while a fresh one loads. The board carries
 *  the viewer's own row, so it is cached per viewer and reloads when the
 *  viewer changes. */
export default function Leaderboard({ onBack }: { onBack?: () => void }) {
  const account = useAuth();
  const [period, setPeriodState] = useState<Period>(tabMemory.period);
  const setPeriod = (p: Period) => { tabMemory.period = p; setPeriodState(p); };
  const { value: res, reload } = useCachedResource<Loaded<Board>>(
    `${viewerScope(account)}:board:${period}`, () => fetchLeaderboard(period));
  const phone = !useMediaQuery(WIDE);
  const scroller = useTabScroll(`leaderboard:${period}`, res !== null);

  let body;
  let pinned = null;
  if (res === null) body = <SkeletonRows kind="board" rows={5} />;
  else if (!res.ok) {
    body = (
      <>
        <p className="lobby-error" role="alert">Could not load the leaderboard ({res.status || "no connection"}).</p>
        {/* the server is out of reach, so the guest's sign-in card shows unavailable */}
        {account.status === "error" ? (
          <div className="signin-card compact lb-rated"><h3>Sign in to be ranked</h3><SignInUnavailable /></div>
        ) : null}
      </>
    );
  } else {
    const { players, me } = res.data;
    const empty = players.length === 0;
    body = (
      <>
        <Rows board={res.data} />
        {empty ? (
          <p className="lb-note">
            {period === "week" ? "Nobody has played a ranked round this week yet." : "No ranked rounds yet."}
          </p>
        ) : null}
      </>
    );
    if (me !== null && !players.some((p) => p.you)) {
      pinned = <ul className="grp lb-list"><Row row={me} /></ul>;
    }
  }
  // a guest's card follows the board, where it is seen at once, rather than
  // pinned to the screen's bottom
  const signIn = account.status === "out" && account.clientId ? <SignInToRank clientId={account.clientId} /> : null;
  if (signIn) pinned = null;

  return (
    <LargeTitlePage className="lb-page" scroller={scroller} title="Leaderboard" phone={phone} onRefresh={reload}
                    before={onBack ? <button className="btn subtle games-back home-back" onClick={onBack}>‹ Back to game</button> : null}>
      <Segmented label="Period" options={PERIODS} value={period} onChange={setPeriod} />
      {body}
      {signIn}
      {pinned ? <div className="lb-pin">{pinned}</div> : null}
    </LargeTitlePage>
  );
}
