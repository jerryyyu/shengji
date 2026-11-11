import { useEffect, useState } from "react";
import { deltaText, fetchStats, setVisibility, signed } from "../ratings/api";
import type { Loaded, MyStats as Stats, RecentGame } from "../ratings/api";
import { closeRatings, openRatings } from "../ratings/route";
import { GamesHead, GamesNotice } from "./GamesStatus";

/** The rating over the account's recent rounds as one inline line. */
export function Sparkline({ points }: { points: number[] }) {
  if (points.length < 2) return null;
  const lo = Math.min(...points);
  const hi = Math.max(...points);
  const span = Math.max(hi - lo, 1);
  const step = 300 / (points.length - 1);
  const coords = points
    .map((p, i) => `${(i * step).toFixed(1)},${(58 - ((p - lo) / span) * 52).toFixed(1)}`)
    .join(" ");
  return (
    <div className="stats-spark">
      <svg viewBox="0 0 300 64" preserveAspectRatio="none" role="img"
           aria-label={`Rating from ${points[0]} to ${points[points.length - 1]}`}>
        <polyline fill="none" stroke="currentColor" strokeWidth="2.5" vectorEffect="non-scaling-stroke"
                  strokeLinejoin="round" points={coords} />
      </svg>
    </div>
  );
}

function pct(value: number | null): string {
  return value === null ? "—" : `${Math.round(value)}%`;
}

function day(unix: number): string {
  const then = new Date(unix * 1000);
  const today = new Date();
  const start = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((start(today) - start(then)) / 86400000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function gameLabel(g: RecentGame): string {
  const partner = g.partner_bot ? "With a bot partner" : `With ${g.partner ?? "a guest"}`;
  const opponents = g.opponents_bots === 2 ? " vs bots" : g.opponents_bots === 0 ? " vs players" : " vs a bot and a player";
  return partner + opponents;
}

function gameMeta(g: RecentGame): string {
  const parts = [day(g.ended_at), `${g.rounds} round${g.rounds === 1 ? "" : "s"}`];
  if (g.games_won > 0) parts.push(g.games_won === 1 ? "won a game" : `won ${g.games_won} games`);
  return parts.join(" · ");
}

function Body({ stats }: { stats: Stats }) {
  const [visible, setVisible] = useState(stats.visible);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toggle = () => {
    const next = !visible;
    setBusy(true);
    setError(null);
    setVisibility(next)
      .then((stored) => setVisible(stored))
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };
  const sub = stats.rank !== null
    ? `Rating · #${stats.rank} all time · ${stats.rounds} round${stats.rounds === 1 ? "" : "s"}`
    : "Rating · no rated rounds yet";
  return (
    <>
      <div className="stats-big">
        <span className="stats-rating">{stats.rating}</span>
        <span className="stats-sub">{sub}</span>
        {stats.provisional && stats.rounds > 0 ? (
          <span className="stats-sub">Provisional until 20 rounds</span>
        ) : null}
      </div>
      <Sparkline points={stats.history} />
      {stats.rounds === 0 ? (
        <GamesNotice title="No rated rounds yet">
          <p>Every round you finish while signed in moves your rating.</p>
        </GamesNotice>
      ) : (
        <div className="stats-tiles">
          <div className="stats-tile"><b>{stats.levels_per_round === null ? "—" : signed(stats.levels_per_round)}</b><span>levels per round</span></div>
          <div className="stats-tile"><b>{pct(stats.won_pct)}</b><span>rounds won</span></div>
          <div className="stats-tile"><b>{pct(stats.defender_won_pct)}</b><span>won as defenders</span></div>
          <div className="stats-tile"><b>{pct(stats.attacker_won_pct)}</b><span>won as attackers</span></div>
          <div className="stats-tile"><b>{stats.best_streak}</b><span>best win streak</span></div>
          <div className="stats-tile"><b>{stats.games_won}</b><span>games won (to A)</span></div>
        </div>
      )}
      {stats.recent_games.length > 0 ? (
        <div className="games-section">
          <span className="field-label">Recent games</span>
          <ul className="lb-list">
            {stats.recent_games.map((g, i) => (
              <li key={i} className="lb-row game">
                <span className="lb-name">
                  <span className="lb-name-text">{gameLabel(g)}</span>
                  <span className="lb-meta">{gameMeta(g)}</span>
                </span>
                <span className={`lb-rating ${g.delta > 0 ? "delta-up" : g.delta < 0 ? "delta-dn" : "delta-flat"}`}>
                  {g.delta > 0 ? `+${g.delta}` : g.delta < 0 ? `−${Math.abs(g.delta)}` : "±0"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {stats.week_delta !== 0 ? (
        <p className="lb-note">This week {deltaText(stats.week_delta)}</p>
      ) : null}
      <button className="stats-toggle" role="switch" aria-checked={visible} disabled={busy} onClick={toggle}>
        <span>Show me on the leaderboard</span>
        <span className={`stats-switch${visible ? " on" : ""}`} aria-hidden="true" />
      </button>
      {error ? <div className="lobby-error" role="alert">{error}</div> : null}
    </>
  );
}

/** My stats: the account's rating, its history and results by role. */
export default function MyStats({ inGame }: { inGame: boolean }) {
  const [res, setRes] = useState<Loaded<Stats> | null>(null);
  useEffect(() => {
    let live = true;
    fetchStats().then((r) => { if (live) setRes(r); });
    return () => { live = false; };
  }, []);
  let body;
  if (res === null) body = <GamesNotice title="Loading…" />;
  else if (!res.ok) {
    body = res.reason === "signed_out"
      ? <GamesNotice title="Sign in to see your stats." />
      : <p className="lobby-error" role="alert">Could not load your stats ({res.status || "no connection"}).</p>;
  } else body = <Body stats={res.data} />;
  return (
    <div className="screen games-screen">
      <div className="panel games-panel lb-panel">
        <GamesHead back={inGame ? "Back to game" : "Lobby"} onBack={closeRatings} title="My stats" />
        {body}
        <button className="btn big lb-stats-link" onClick={() => openRatings("leaderboard")}>Leaderboard</button>
      </div>
    </div>
  );
}
