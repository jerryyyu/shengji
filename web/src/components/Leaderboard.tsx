import { useEffect, useState } from "react";
import { deltaText, fetchLeaderboard, signed } from "../ratings/api";
import type { Leaderboard as Board, LeaderRow, Loaded, Period } from "../ratings/api";
import { closeRatings, openRatings } from "../ratings/route";
import { GamesHead, GamesNotice } from "./GamesStatus";

function meta(row: LeaderRow): string {
  const rounds = `${row.rounds} round${row.rounds === 1 ? "" : "s"}`;
  return row.provisional ? `${rounds} · provisional` : `${rounds} · ${signed(row.levels_per_round)} lv/round`;
}

export function Row({ row }: { row: LeaderRow }) {
  const top = row.rank !== null && row.rank <= 3;
  return (
    <li className={`lb-row${row.you ? " me" : ""}`}>
      <span className={`lb-rank${top ? " top" : ""}`}>{row.rank ?? "—"}</span>
      <span className="lb-name">
        <span className="lb-name-text">{row.you ? "You" : row.name}</span>
        {row.provisional ? <span className="lb-new" title="Fewer than 20 rated rounds">new</span> : null}
        <span className="lb-meta">{meta(row)}</span>
      </span>
      <span className="lb-rating">
        {row.rating}
        <small className={row.week_delta > 0 ? "delta-up" : row.week_delta < 0 ? "delta-dn" : "delta-flat"}
               title="Change this week">
          {deltaText(row.week_delta)}
        </small>
      </span>
    </li>
  );
}

function Anchor({ name, rating }: { name: string; rating: number }) {
  return (
    <li className="lb-row anchor">
      <span className="lb-rank">—</span>
      <span className="lb-name">
        <span className="lb-name-text">{name}</span>
        <span className="lb-meta">fixed anchor</span>
      </span>
      <span className="lb-rating">{rating}</span>
    </li>
  );
}

/** The top players with the bot anchor placed where its rating falls, and
 *  the viewer's own row pinned below when it is not among them. */
function Rows({ board }: { board: Board }) {
  const { players, me, anchor } = board;
  const at = players.findIndex((p) => p.rating < anchor.rating);
  const split = at === -1 ? players.length : at;
  const pinned = me !== null && !players.some((p) => p.you);
  return (
    <ul className="lb-list">
      {players.slice(0, split).map((p, i) => <Row key={`a${i}`} row={p} />)}
      <Anchor {...anchor} />
      {players.slice(split).map((p, i) => <Row key={`b${i}`} row={p} />)}
      {pinned ? (
        <>
          <li className="lb-gap" aria-hidden="true">· · ·</li>
          <Row row={me} />
        </>
      ) : null}
    </ul>
  );
}

/** The leaderboard: signed-in players by rating, this week or all time. */
export default function Leaderboard({ inGame }: { inGame: boolean }) {
  const [period, setPeriod] = useState<Period>("week");
  const [res, setRes] = useState<Loaded<Board> | null>(null);
  useEffect(() => {
    let live = true;
    setRes(null);
    fetchLeaderboard(period).then((r) => { if (live) setRes(r); });
    return () => { live = false; };
  }, [period]);

  let body;
  if (res === null) body = <GamesNotice title="Loading…" />;
  else if (!res.ok) {
    body = res.reason === "signed_out"
      ? <GamesNotice title="Sign in to see the leaderboard." />
      : <p className="lobby-error" role="alert">Could not load the leaderboard ({res.status || "no connection"}).</p>;
  } else {
    const empty = res.data.players.length === 0 && res.data.me === null;
    body = (
      <>
        <Rows board={res.data} />
        {empty ? (
          <p className="lb-note">
            {period === "week" ? "Nobody has played a rated round this week yet." : "No rated rounds yet."}
          </p>
        ) : null}
      </>
    );
  }
  return (
    <div className="screen games-screen">
      <div className="panel games-panel lb-panel">
        <GamesHead back={inGame ? "Back to game" : "Lobby"} onBack={closeRatings} title="Leaderboard"
                   sub="Signed-in players, rated every round" />
        <div className="lb-seg" role="group" aria-label="Period">
          {(["week", "all"] as const).map((p) => (
            <button key={p} className={`lb-seg-btn${period === p ? " on" : ""}`} aria-pressed={period === p}
                    onClick={() => setPeriod(p)}>
              {p === "week" ? "This week" : "All time"}
            </button>
          ))}
        </div>
        {body}
        <button className="btn big lb-stats-link" onClick={() => openRatings("stats")}>My stats</button>
      </div>
    </div>
  );
}
