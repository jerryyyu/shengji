import { useEffect, useState } from "react";
import { useAuth } from "../auth";
import { fetchLeaderboard } from "../ratings/api";
import type { Leaderboard as Board, LeaderRow, Loaded, Period } from "../ratings/api";
import { Segmented } from "../home/HomeShell";
import { tabMemory, useCachedResource, useTabScroll, viewerScope } from "../home/session";
import { WIDE } from "../home/route";
import LargeTitlePage from "../home/LargeTitlePage";
import { useMediaQuery } from "../phoneLayout";
import { guestName } from "../guestName";
import { SkeletonRows } from "./GamesList";
import { useScreen } from "../telemetry";

const PERIODS = [
  { value: "week", label: "This week" },
  { value: "all", label: "All time" },
] as const;

/** A rating as read aloud: 1,042, with the thousands separator. */
export function ratingText(rating: number): string {
  return rating.toLocaleString("en-US");
}

/** A week's rating change as drawn: ▲18, ▼6, or a dash for none. */
export function weekMove(delta: number): { text: string; spoken: string; dir: "up" | "down" | "flat" } {
  const n = Math.round(delta);
  if (n > 0) return { text: `\u25B2${n}`, spoken: `up ${n} this week`, dir: "up" };
  if (n < 0) return { text: `\u25BC${-n}`, spoken: `down ${-n} this week`, dir: "down" };
  return { text: "\u2013", spoken: "no change this week", dir: "flat" };
}

/** One player. The top three's ranks sit on gold, silver and bronze discs;
 *  on This week (`week`) the row ends in the week's movement. */
export function Row({ row, week = false }: { row: LeaderRow; week?: boolean }) {
  const top = row.rank !== null && row.rank <= 3;
  const move = week ? weekMove(row.week_delta) : null;
  return (
    <li className={`lb-row${row.you ? " me" : ""}`}>
      <span className={`lb-rank${top ? ` top medal-${row.rank}` : ""}`}>{row.rank ?? "—"}</span>
      <span className="avatar avatar-sm" aria-hidden="true">{row.name.slice(0, 1).toUpperCase()}</span>
      <span className="lb-name">
        <span className="lb-name-text" title={row.name}>{row.name}</span>
        {/* its own box, so a long name truncates before it */}
        {row.you ? <span className="lb-you">{" (you)"}</span> : null}
        {row.provisional ? <span className="lb-new" title="Fewer than 20 ranked rounds">new</span> : null}
      </span>
      <span className="lb-rating">{ratingText(row.rating)}</span>
      {move ? (
        <span className={`lb-move ${move.dir}`}>
          <span aria-hidden="true">{move.text}</span>
          <span className="sr-only">{`, ${move.spoken}`}</span>
        </span>
      ) : null}
    </li>
  );
}

/** The top players by rating. */
function Rows({ board }: { board: Board }) {
  return (
    <ul className="grp lb-list">
      {board.players.map((p, i) => <Row key={i} row={p} week={board.period === "week"} />)}
    </ul>
  );
}

/** Under the board for a guest: one row that opens the identity sheet.
 *  What ranked play means is How to play's to say. */
function SignInToRank() {
  return (
    <ul className="grp lb-rated">
      <li>
        <button type="button" className="grp-row lb-signin" onClick={() => guestName.open("leaderboard_row")}>
          <span className="grp-label">Sign in to be ranked</span>
          <span className="grp-value chev" />
        </button>
      </li>
    </ul>
  );
}

/** The Leaderboard tab: ranked players by rating, this week or all time.
 *  Guests read it too; the viewer's own row (or, for a guest, the Sign in
 *  row) is pinned to the bottom when it is not among the rows shown.
 *  This week on the first visit, unless nobody has played a ranked round
 *  this week yet: then it opens on All time; after that the period last
 *  chosen, with the last board shown at once while a fresh one loads. The board carries
 *  the viewer's own row, so it is cached per viewer and reloads when the
 *  viewer changes. */
export default function Leaderboard() {
  useScreen("leaderboard");
  const account = useAuth();
  const [period, setPeriodState] = useState<Period>(tabMemory.period);
  const setPeriod = (p: Period) => { tabMemory.period = p; tabMemory.periodChosen = true; setPeriodState(p); };
  const { value: res, reload } = useCachedResource<Loaded<Board>>(
    `${viewerScope(account)}:board:${period}`, () => fetchLeaderboard(period));
  const phone = !useMediaQuery(WIDE);
  const scroller = useTabScroll(`leaderboard:${period}`, res !== null);
  // an empty week is a dead end: the board opens on All time instead, until
  // the viewer picks a period themselves
  const emptyWeek = period === "week" && res !== null && res.ok && res.data.players.length === 0;
  useEffect(() => {
    if (!emptyWeek || tabMemory.periodChosen) return;
    tabMemory.period = "all";
    setPeriodState("all");
  }, [emptyWeek]);

  let body;
  let pinned = null;
  if (res === null) body = <SkeletonRows kind="board" rows={5} />;
  else if (!res.ok) {
    body = <p className="lobby-error" role="alert">Could not load the leaderboard ({res.status || "no connection"}).</p>;
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
      pinned = <ul className="grp lb-list"><Row row={me} week={res.data.period === "week"} /></ul>;
    }
  }
  // a guest's row follows the board, where it is seen at once, rather than
  // pinned to the screen's bottom; with sign-in out of reach the row stays
  // and the sheet shows its buttons unavailable
  const signIn = (account.status === "out" && account.clientId) || account.status === "error"
    ? <SignInToRank /> : null;
  if (signIn) pinned = null;

  return (
    <LargeTitlePage className="lb-page" scroller={scroller} title="Leaderboard" phone={phone} onRefresh={reload}>
      <Segmented label="Period" options={PERIODS} value={period} onChange={setPeriod} />
      {body}
      {signIn}
      {pinned ? <div className="lb-pin">{pinned}</div> : null}
    </LargeTitlePage>
  );
}
