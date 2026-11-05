import { useCallback, useEffect, useRef, useState } from "react";
import { fetchGame, fetchGames, removeGame, teamPair } from "../replay/api";
import type { Fetched, GameDetail, GameRow } from "../replay/api";
import { navigate } from "../replay/route";
import type { GamesRoute } from "../replay/route";
import { GamesUnavailable, SignInPrompt } from "./GamesStatus";
import ReplayView from "./ReplayView";

function when(unix: number): string {
  return new Date(unix * 1000).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

function nameAt(game: GameRow, seat: number): string {
  return game.players[seat] ?? `Seat ${seat + 1}`;
}

/** "You & Partner vs A, B", with the viewer's team marked. */
function Teams({ game }: { game: GameRow }) {
  const me = game.seat;
  const partner = (me + 2) % 4;
  const opp = [(me + 1) % 4, (me + 3) % 4];
  return (
    <span className="games-teams">
      <span className={`games-team mine team${me % 2}`} title="Your team">
        {nameAt(game, me)} (you) &amp; {nameAt(game, partner)}
      </span>
      <span className="games-vs">vs</span>
      <span className={`games-team team${(me + 1) % 2}`}>
        {opp.map((s) => nameAt(game, s)).join(", ")}
      </span>
    </span>
  );
}

function Summary({ game }: { game: GameRow }) {
  const mine = game.seat % 2;
  const levels = teamPair(game.final_levels);
  const won = teamPair(game.games_won);
  const n = game.rounds.length;
  return (
    <span className="games-meta">
      <span>{n} round{n === 1 ? "" : "s"}</span>
      {levels ? <span>Levels: you {levels[mine]} · them {levels[1 - mine]}</span> : null}
      {won ? <span>Games won: {won[mine]}–{won[1 - mine]}</span> : null}
      {game.incomplete ? <span className="games-tag">incomplete</span> : null}
    </span>
  );
}

function roundLine(seat: number, result: Record<string, unknown> | undefined): string {
  if (!result) return "unfinished";
  const mine = seat % 2;
  const won = Number(result.winner_team) === mine;
  const change = Number(result.level_change) || 0;
  const pts = result.attacker_points;
  return `${won ? "won" : "lost"}${change ? `, +${change} level${change === 1 ? "" : "s"}` : ""}`
    + (pts !== undefined ? ` · attackers ${String(pts)}` : "");
}

function GameView({ id, onRemoved }: { id: string; onRemoved: (id: string) => void }) {
  const [res, setRes] = useState<Fetched<GameDetail> | null>(null);
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  useEffect(() => {
    let live = true;
    setRes(null);
    fetchGame(id).then((r) => { if (live) setRes(r); });
    return () => { live = false; };
  }, [id]);
  useEffect(() => () => { if (timer.current !== null) window.clearTimeout(timer.current); }, []);

  const remove = () => {
    if (!armed) {
      setArmed(true);
      timer.current = window.setTimeout(() => { timer.current = null; setArmed(false); }, 3000);
      return;
    }
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null; }
    setBusy(true);
    setError(null);
    removeGame(id)
      .then(() => { onRemoved(id); navigate({ page: "list" }); })
      .catch((e: Error) => { setError(e.message); setArmed(false); })
      .finally(() => setBusy(false));
  };

  let body;
  if (res === null) body = <p className="games-empty">Loading…</p>;
  else if (!res.ok) {
    body = res.reason === "signed_out" ? <SignInPrompt />
      : res.reason === "not_found" ? <GamesUnavailable />
      : <p className="lobby-error" role="alert">Could not load the game ({res.status || "no connection"}).</p>;
  } else {
    const game = res.data;
    const results = new Map((game.round_results ?? []).map((r) => [r.round, r]));
    body = (
      <>
        <div className="games-row static">
          <span className="games-when">{when(game.started_at)} · room {game.room_code}</span>
          <Teams game={game} />
          <Summary game={game} />
        </div>
        <ul className="games-rounds">
          {game.rounds.map((n) => {
            const r = results.get(n);
            return (
              <li key={n} className="games-round">
                <span className="games-round-n">Round {n}</span>
                <span className="games-round-res">{roundLine(r?.seat ?? game.seat, r?.result)}</span>
                <button className="btn subtle" onClick={() => navigate({ page: "replay", id, round: n })}>
                  Replay
                </button>
              </li>
            );
          })}
          {game.rounds.length === 0 ? <li className="games-empty">No rounds to replay.</li> : null}
        </ul>
        <button className={`btn danger games-remove${armed ? " armed" : ""}`} disabled={busy} onClick={remove}>
          {busy ? "Removing…" : armed ? "Tap again to remove" : "Remove from my history"}
        </button>
        {error ? <div className="lobby-error" role="alert">{error}</div> : null}
      </>
    );
  }
  return (
    <div className="games-panel">
      <div className="games-head">
        <button className="btn subtle" onClick={() => navigate({ page: "list" })}>‹ My games</button>
        <h2 className="games-title">Game</h2>
      </div>
      {body}
    </div>
  );
}

type ListState =
  | { status: "loading" }
  | { status: "failed"; reason: "signed_out" | "not_found" | "error"; code: number }
  | { status: "ready"; games: GameRow[]; next: number | null; more: boolean; moreError: boolean };

/** "My games": the signed-in account's history, its games, and replays of
 *  their rounds. The list survives a visit to a game, so back is instant. */
export default function GamesList({ route, inGame }: { route: GamesRoute; inGame: boolean }) {
  const [list, setList] = useState<ListState>({ status: "loading" });

  useEffect(() => {
    let live = true;
    fetchGames(null).then((r) => {
      if (!live) return;
      setList(r.ok
        ? { status: "ready", games: r.data.games, next: r.data.next_before, more: false, moreError: false }
        : { status: "failed", reason: r.reason, code: r.status });
    });
    return () => { live = false; };
  }, []);

  const loadMore = () => {
    if (list.status !== "ready" || list.next === null || list.more) return;
    const before = list.next;
    setList({ ...list, more: true, moreError: false });
    fetchGames(before).then((r) => {
      setList((cur) => {
        if (cur.status !== "ready") return cur;
        if (!r.ok) return { ...cur, more: false, moreError: true };
        const seen = new Set(cur.games.map((g) => g.id));
        return { status: "ready", games: [...cur.games, ...r.data.games.filter((g) => !seen.has(g.id))],
                 next: r.data.next_before, more: false, moreError: false };
      });
    });
  };

  const onRemoved = useCallback((id: string) => {
    setList((cur) => (cur.status === "ready" ? { ...cur, games: cur.games.filter((g) => g.id !== id) } : cur));
  }, []);

  let page;
  if (route.page === "replay") page = <ReplayView id={route.id} round={route.round} />;
  else if (route.page === "game") page = <GameView id={route.id} onRemoved={onRemoved} />;
  else {
    let body;
    if (list.status === "loading") body = <p className="games-empty">Loading…</p>;
    else if (list.status === "failed") {
      body = list.reason === "signed_out" ? <SignInPrompt />
        : <p className="lobby-error" role="alert">Could not load your games ({list.code || "no connection"}).</p>;
    } else {
      body = (
        <>
          {list.games.length === 0 ? (
            <p className="games-empty">No saved games yet. Games you play while signed in appear here.</p>
          ) : (
            <ul className="games-list">
              {list.games.map((g) => (
                <li key={g.id}>
                  <button className="games-row" onClick={() => navigate({ page: "game", id: g.id })}>
                    <span className="games-when">{when(g.started_at)}</span>
                    <Teams game={g} />
                    <Summary game={g} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {list.next !== null ? (
            <button className="btn games-more" disabled={list.more} onClick={loadMore}>
              {list.more ? "Loading…" : "Load more"}
            </button>
          ) : null}
          {list.moreError ? <div className="lobby-error" role="alert">Could not load more games.</div> : null}
        </>
      );
    }
    page = (
      <div className="games-panel">
        <div className="games-head">
          <button className="btn subtle" onClick={() => navigate(null)}>{inGame ? "‹ Back to game" : "‹ Lobby"}</button>
          <h2 className="games-title">My games</h2>
        </div>
        {body}
      </div>
    );
  }
  return <div className="screen games-screen">{page}</div>;
}
