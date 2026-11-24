import { useCallback, useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";
import { fetchGame, fetchGames, removeGame, teamPair } from "../replay/api";
import type { Fetched, GameDetail, GameRow, RoundResult } from "../replay/api";
import { navigate } from "../replay/route";
import { continueGame, hasLevels, useCanContinue } from "../replay/continueGame";
import type { GamesRoute } from "../replay/route";
import { GamesHead, GamesNotice, GamesUnavailable, SignInPrompt } from "./GamesStatus";
import ReplayView from "./ReplayView";
import ConfirmSheet from "./ConfirmSheet";
import { dayLabel } from "../home/dayLabel";
import { cached, remember } from "../home/session";
import { deltaText } from "../ratings/api";
import { useScreen } from "../telemetry";
import { t, tx, useT } from "../i18n";

function deltaClass(delta: number): string {
  return delta > 0 ? "delta-up" : delta < 0 ? "delta-dn" : "delta-flat";
}

/** The viewer's rating change, ▲/▼ as on the leaderboard; nothing for an
 *  unrated round or game. */
export function RatingDelta({ delta, className = "" }: { delta?: number; className?: string }) {
  if (delta === undefined) return null;
  return <span className={`rating-change ${deltaClass(delta)} ${className}`.trim()}>{deltaText(delta)}</span>;
}

function when(unix: number): string {
  return new Date(unix * 1000).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

function nameAt(game: GameRow, seat: number): string {
  return game.players[seat] ?? t("me.games.seat", { n: seat + 1 });
}

/** Placeholder rows while a list loads, built from the real rows' own
 *  classes so each is the height of the row that replaces it. Screen readers
 *  hear "Loading…" once; the bars are hidden from them. */
export function SkeletonRows({ kind, rows = 3 }: { kind: "games" | "rounds" | "board"; rows?: number }) {
  const t = useT();
  const keys = Array.from({ length: rows }, (_, k) => k);
  let list;
  if (kind === "board") {
    list = (
      <ul className="grp lb-list skel-list" aria-hidden="true">
        {keys.map((k) => (
          <li key={k} className="lb-row skel-row">
            <span className="lb-rank"><span className="skel skel-rank" /></span>
            <span className="avatar avatar-sm skel" />
            <span className="lb-name"><span className="skel skel-name" /></span>
            <span className="lb-rating"><span className="skel skel-num" /></span>
          </li>
        ))}
      </ul>
    );
  } else if (kind === "rounds") {
    list = (
      <ul className="games-rounds skel-list" aria-hidden="true">
        {keys.map((k) => (
          <li key={k} className="games-round skel-row">
            <span className="games-round-n"><span className="skel skel-name" /></span>
            <span className="games-round-res"><span className="skel skel-sub" /></span>
            <span className="btn subtle skel-ghost">{t("me.games.replay")}</span>
          </li>
        ))}
      </ul>
    );
  } else {
    list = (
      <ul className="grp games-day-list skel-list" aria-hidden="true">
        {keys.map((k) => (
          <li key={k} className="games-day-item">
            <div className="grp-row games-day-row skel-row">
              <span className="games-row-main">
                <span><span className="skel skel-title" /></span>
                <span className="games-row-sub"><span className="skel skel-sub" /></span>
              </span>
            </div>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <div className="skel-wrap" role="status">
      <span className="skel-sr">{t("common.loading")}</span>
      {list}
    </div>
  );
}

/** "You & Partner vs A, B", with the viewer's team marked. */
function Teams({ game }: { game: GameRow }) {
  const t = useT();
  const me = game.seat;
  const partner = (me + 2) % 4;
  const opp = [(me + 1) % 4, (me + 3) % 4];
  return (
    <span className="games-teams">
      <span className={`games-team mine team${me % 2}`} title={t("me.games.yourTeam")}>
        {t("me.games.mineTeam", { me: nameAt(game, me), partner: nameAt(game, partner) })}
      </span>
      <span className="games-vs">{t("me.games.vs")}</span>
      <span className={`games-team team${(me + 1) % 2}`}>
        {t("me.games.pair", { a: nameAt(game, opp[0]), b: nameAt(game, opp[1]) })}
      </span>
    </span>
  );
}

function Summary({ game }: { game: GameRow }) {
  const t = useT();
  const mine = game.seat % 2;
  const levels = teamPair(game.final_levels);
  const won = teamPair(game.games_won);
  const n = game.rounds.length;
  return (
    <span className="games-meta">
      <span>{t("me.games.rounds", { n })}</span>
      {levels ? <span>{t("me.games.levels", { a: levels[mine], b: levels[1 - mine] })}</span> : null}
      {won ? <span>{t("me.games.gamesWon", { a: won[mine], b: won[1 - mine] })}</span> : null}
      {game.rating_change !== undefined ? (
        <span className="games-meta-rating">
          {tx("me.games.rating", { delta: <RatingDelta delta={game.rating_change} /> })}
          {game.rating_after !== undefined ? <> · {game.rating_after.toLocaleString()}</> : null}
        </span>
      ) : null}
      {game.incomplete ? <span className="games-tag">{t("me.games.incomplete")}</span> : null}
    </span>
  );
}

/** "Level 6 · Defender · Won": the rank played, the viewer's side, the result. */
function roundLine(row: RoundResult | undefined): string {
  if (!row) return t("me.games.unfinished");
  const mine = row.seat % 2;
  const parts: string[] = [];
  if (row.level !== undefined) parts.push(t("me.games.level", { level: row.level }));
  if (row.banker !== undefined) parts.push(t(row.banker % 2 === mine ? "me.games.defender" : "me.games.attacker"));
  parts.push(t(Number(row.result.winner_team) === mine ? "me.games.won" : "me.games.lost"));
  return parts.join(" · ");
}

/** A saved game's Continue: a new table at its last levels, shown only
 *  when the record has them. Replays are per round, in the game's list. */
function ContinueGame({ game }: { game: GameRow }) {
  const t = useT();
  const can = useCanContinue();
  if (!hasLevels(game)) return null;
  return (
    <div className="games-actions">
      <button type="button" className="btn gold games-continue" disabled={!can}
              title={can ? undefined : t("me.games.continueBlocked")}
              onClick={() => continueGame(game.id)}>
        {t("me.games.continue")}
      </button>
    </div>
  );
}

function GameView({ id }: { id: string }) {
  const t = useT();
  const [res, setRes] = useState<Fetched<GameDetail> | null>(null);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setRes(null);
    fetchGame(id).then((r) => { if (live) setRes(r); });
    return () => { live = false; };
  }, [id]);

  // the confirm sheet's Remove: the sheet holds still until the server answers
  const remove = () => {
    setBusy(true);
    setError(null);
    removeGame(id)
      .then(() => { forgetRemovedGame(id); navigate({ page: "list" }); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };

  let body;
  let sub: string | undefined;
  if (res === null) body = <SkeletonRows kind="rounds" />;
  else if (!res.ok) {
    body = res.reason === "signed_out" ? <SignInPrompt />
      : res.reason === "not_found" ? <GamesUnavailable />
      : <p className="lobby-error" role="alert">{t("me.games.gameFailed", { status: res.status || t("me.noConnection") })}</p>;
  } else {
    const game = res.data;
    const results = new Map((game.round_results ?? []).map((r) => [r.round, r]));
    sub = when(game.started_at);
    body = (
      <>
        <div className="games-row static">
          <Teams game={game} />
          <Summary game={game} />
        </div>
        <ContinueGame game={game} />
        <div className="games-section">
          <span className="field-label">{t("me.games.roundsHead")}</span>
          <ul className="games-rounds">
            {game.rounds.map((n) => {
              const r = results.get(n);
              return (
                <li key={n} className="games-round">
                  <span className="games-round-n">{t("me.games.round", { n })}</span>
                  <span className="games-round-res">{roundLine(r)}</span>
                  <RatingDelta delta={r?.rating_delta} className="games-round-delta" />
                  <button className="btn subtle" onClick={() => navigate({ page: "replay", id, round: n })}>
                    {t("me.games.replay")}
                  </button>
                </li>
              );
            })}
            {game.rounds.length === 0 ? <li className="games-round-res">{t("me.games.noRounds")}</li> : null}
          </ul>
        </div>
        <button className="btn danger games-remove" onClick={() => setAsking(true)}>{t("me.games.remove")}</button>
        {asking ? (
          <ConfirmSheet title={t("me.games.removeTitle")} cancel={t("common.cancel")}
                        confirm={busy ? t("me.games.removing") : t("me.games.removeConfirm")} danger
                        busy={busy} error={error} className="games-remove-confirm"
                        onConfirm={remove} onCancel={() => { setAsking(false); setError(null); }} />
        ) : null}
      </>
    );
  }
  return (
    <div className="panel games-panel">
      <GamesHead back={t("me.section.games")} onBack={() => navigate({ page: "list" })} title={t("me.games.game")}
                 sub={sub} />
      {body}
    </div>
  );
}

type ListState =
  | { status: "loading" }
  | { status: "failed"; reason: "signed_out" | "not_found" | "error"; code: number }
  | { status: "ready"; games: GameRow[]; next: string | null; more: boolean; moreError: boolean };

// Every cache key a list has been shown under, and the lists on screen, so a
// removed game leaves all of them (every loaded page) and never reappears
// from a cached copy.
const listKeys = new Set<string>();
const shownLists = new Set<(id: string) => void>();

function withoutGame(list: ListState, id: string): ListState {
  return list.status === "ready" ? { ...list, games: list.games.filter((g) => g.id !== id) } : list;
}

function forgetRemovedGame(id: string): void {
  for (const key of listKeys) {
    const list = cached<ListState>(key);
    if (list) remember(key, withoutGame(list, id));
  }
  for (const drop of shownLists) drop(id);
}

function clock(unix: number): string {
  return new Date(unix * 1000).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

/** "You & Ann vs Bot 1, Bea": the teams, yours first. */
function gameTitle(game: GameRow): string {
  const me = game.seat;
  return t("me.games.title", {
    partner: nameAt(game, (me + 2) % 4), a: nameAt(game, (me + 1) % 4), b: nameAt(game, (me + 3) % 4),
  });
}

function gameSub(game: GameRow): string {
  const mine = game.seat % 2;
  const levels = teamPair(game.final_levels);
  const n = game.rounds.length;
  const parts = [clock(game.started_at), t("me.games.rounds", { n })];
  if (levels) parts.push(t("me.games.levels", { a: levels[mine], b: levels[1 - mine] }));
  return parts.join(" · ");
}

/** Consecutive games that started on the same local day. */
function byDay(games: GameRow[]): { label: string; games: GameRow[] }[] {
  const out: { label: string; games: GameRow[] }[] = [];
  for (const g of games) {
    const label = dayLabel(g.started_at);
    const last = out[out.length - 1];
    if (last && last.label === label) last.games.push(g);
    else out.push({ label, games: [g] });
  }
  return out;
}

/** The signed-in account's saved games, newest first and grouped by day;
 *  a whole row is one tap that opens the game, which holds its Continue and
 *  a Replay for each round. With a `cacheKey` the last list shown is
 *  drawn at once on return and refreshed underneath; `onReady` fires once the list (or its failure) is drawn.
 *  `refreshRef` receives the first-page reload, for a pull to refresh. */
export function SavedGames({ onPlay, cacheKey, onReady, refreshRef }: {
  onPlay: () => void; cacheKey?: string; onReady?: () => void;
  refreshRef?: MutableRefObject<(() => Promise<void>) | null>;
}) {
  const t = useT();
  const [list, setList] = useState<ListState>(
    () => (cacheKey ? cached<ListState>(cacheKey) : undefined) ?? { status: "loading" });

  useEffect(() => {
    if (cacheKey) listKeys.add(cacheKey);
  }, [cacheKey]);

  useEffect(() => {
    const drop = (id: string) => setList((cur) => withoutGame(cur, id));
    shownLists.add(drop);
    return () => { shownLists.delete(drop); };
  }, []);

  // the first page, merged over what is shown: on mount, and on a pull to
  // refresh. Only the newest request is merged, so an older one landing after
  // a pull to refresh cannot put stale rows back.
  const live = useRef(false);
  const firstPageTicket = useRef(0);
  const loadFirstPage = useCallback((): Promise<void> => {
    const ticket = ++firstPageTicket.current;
    return fetchGames(null).then((r) => {
      if (!live.current || ticket !== firstPageTicket.current) return;
      setList((cur) => {
        if (!r.ok) return cur.status === "ready" ? cur : { status: "failed", reason: r.reason, code: r.status };
        const fresh = r.data.games;
        // a first page with no continuation is the whole list
        if (r.data.next_before === null) {
          return { status: "ready", games: fresh, next: null, more: false, moreError: false };
        }
        // pages loaded past the first stay, below the refreshed first page
        const ids = new Set(fresh.map((g) => g.id));
        const oldest = fresh.length ? fresh[fresh.length - 1].started_at : Infinity;
        const older = cur.status === "ready"
          ? cur.games.filter((g) => !ids.has(g.id) && g.started_at < oldest) : [];
        return { status: "ready", games: [...fresh, ...older], next: older.length && cur.status === "ready"
          ? cur.next : r.data.next_before, more: false, moreError: false };
      });
    });
  }, []);

  useEffect(() => {
    live.current = true;
    void loadFirstPage();
    return () => { live.current = false; };
  }, [loadFirstPage]);

  useEffect(() => {
    if (!refreshRef) return;
    refreshRef.current = loadFirstPage;
    return () => { if (refreshRef.current === loadFirstPage) refreshRef.current = null; };
  }, [refreshRef, loadFirstPage]);

  useEffect(() => {
    if (list.status === "loading") return;
    if (cacheKey && list.status === "ready" && !list.more) remember(cacheKey, list);
    onReady?.();
  }, [list, cacheKey, onReady]);

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

  if (list.status === "loading") return <SkeletonRows kind="games" />;
  if (list.status === "failed") {
    return list.reason === "signed_out" ? <SignInPrompt />
      : <p className="lobby-error" role="alert">{t("me.games.listFailed", { status: list.code || t("me.noConnection") })}</p>;
  }
  if (list.games.length === 0) {
    return (
      <GamesNotice title={t("me.games.empty")}>
        <p>{t("me.games.emptyLine")}</p>
        <button className="btn gold big games-cta" onClick={onPlay}>{t("me.games.play")}</button>
      </GamesNotice>
    );
  }
  return (
    <div className="games-days">
      {byDay(list.games).map((d) => (
        <section key={`${d.label}-${d.games[0].id}`} className="grp-section">
          <h3 className="grp-head">{d.label}</h3>
          <ul className="grp games-day-list">
            {d.games.map((g) => (
              <li key={g.id} className="games-day-item">
                <button className="grp-row games-day-row" onClick={() => navigate({ page: "game", id: g.id })}>
                  <span className="games-row-main">
                    <span className="games-row-title" title={gameTitle(g)}>{gameTitle(g)}</span>
                    <span className="games-row-sub">
                      {gameSub(g)}
                      {g.incomplete ? <span className="games-tag">{t("me.games.incomplete")}</span> : null}
                    </span>
                  </span>
                  {g.rating_change !== undefined ? (
                    <span className="games-row-rating">
                      <RatingDelta delta={g.rating_change} />
                      {g.rating_after !== undefined ? (
                        <span className="games-row-rating-after">{g.rating_after.toLocaleString()}</span>
                      ) : null}
                    </span>
                  ) : null}
                  <span className="grp-value chev" aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {list.next !== null ? (
        <button className="btn games-more" disabled={list.more} onClick={loadMore}>
          {list.more ? t("common.loading") : t("me.games.loadMore")}
        </button>
      ) : null}
      {list.moreError ? <div className="lobby-error" role="alert">{t("me.games.moreFailed")}</div> : null}
    </div>
  );
}

/** A saved game's rounds and the replay of one; the list itself is the Me
 *  tab's Games section. */
export default function GamesList({ route }: { route: GamesRoute }) {
  useScreen(route.page === "list" ? "games" : "game");
  let page;
  if (route.page === "replay") page = <ReplayView id={route.id} round={route.round} />;
  else if (route.page === "game") page = <GameView id={route.id} />;
  else page = null;
  return <div className="screen games-screen">{page}</div>;
}
