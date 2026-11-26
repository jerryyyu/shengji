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
import { t, useT } from "../i18n";
import { Portrait } from "../companion/Companion";
import { useCollection } from "../companion/feature";

/** A rating as read aloud: 1,042, with the thousands separator. */
export function ratingText(rating: number): string {
  return rating.toLocaleString("en-US");
}

/** Places moved this week as drawn: ▲3, ▼1, or a dash for none; nothing for
 *  a player new this week. */
function weekMove(places: number | null): { text: string; spoken: string; dir: "up" | "down" | "flat" } | null {
  if (places === null) return null;
  const n = Math.round(places);
  if (n > 0) return { text: `\u25B2${n}`, spoken: t("me.board.moveUp", { n }), dir: "up" };
  if (n < 0) return { text: `\u25BC${-n}`, spoken: t("me.board.moveDown", { n: -n }), dir: "down" };
  return { text: "\u2013", spoken: t("me.board.moveFlat"), dir: "flat" };
}

/** One player. The top three's ranks sit on gold, silver and bronze discs;
 *  on This week (`week`) the row ends in the places it moved this week. */
export function Row({ row, week = false }: { row: LeaderRow; week?: boolean }) {
  const t = useT();
  const top = row.rank !== null && row.rank <= 3;
  const move = week ? weekMove(row.week_rank_move) : null;
  const companions = useCollection();
  return (
    <li className={`lb-row${row.you ? " me" : ""}`}>
      <span className={`lb-rank${top ? ` top medal-${row.rank}` : ""}`}>{row.rank ?? "—"}</span>
      {companions
        ? <span className="avatar avatar-sm avatar-portrait" aria-hidden="true"><Portrait look={row.look} size={28} /></span>
        : <span className="avatar avatar-sm" aria-hidden="true">{row.name.slice(0, 1).toUpperCase()}</span>}
      <span className="lb-name">
        <span className="lb-name-text" title={row.name}>{row.name}</span>
        {/* its own box, so a long name truncates before it */}
        {row.you ? <span className="lb-you">{t("me.board.you")}</span> : null}
        {row.provisional ? <span className="lb-new" title={t("me.board.newTitle")}>{t("me.board.new")}</span> : null}
      </span>
      <span className="lb-rating">{ratingText(row.rating)}</span>
      {move ? (
        <span className={`lb-move ${move.dir}`}>
          <span aria-hidden="true">{move.text}</span>
          <span className="sr-only">{t("me.board.moveSpoken", { move: move.spoken })}</span>
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
  const t = useT();
  return (
    <ul className="grp lb-rated">
      <li>
        <button type="button" className="grp-row lb-signin" onClick={() => guestName.open("leaderboard_row")}>
          <span className="grp-label">{t("me.board.signIn")}</span>
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
  const t = useT();
  const periods = [
    { value: "week", label: t("me.board.week") },
    { value: "all", label: t("me.board.all") },
  ] as const;
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
    body = <p className="lobby-error" role="alert">{t("me.board.failed", { status: res.status || t("me.noConnection") })}</p>;
  } else {
    const { players, me } = res.data;
    const empty = players.length === 0;
    body = (
      <>
        <Rows board={res.data} />
        {empty ? (
          <p className="lb-note">
            {period === "week" ? t("me.board.emptyWeek") : t("me.board.emptyAll")}
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
    <LargeTitlePage className="lb-page" scroller={scroller} title={t("me.board.title")} phone={phone} onRefresh={reload}>
      <Segmented label={t("me.board.period")} options={periods} value={period} onChange={setPeriod} />
      {body}
      {signIn}
      {pinned ? <div className="lb-pin">{pinned}</div> : null}
    </LargeTitlePage>
  );
}
