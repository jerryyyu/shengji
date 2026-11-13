import type { GameState, RoundResult } from "../protocol";
import { conn } from "../ws";
import Card from "./Card";
import { useId, useState } from "react";
import { useAuth } from "../auth";
import GoogleSignIn from "./GoogleSignIn";
import ResultDialog from "./ResultDialog";
import LeaveAlert from "./LeaveAlert";
import { OFFLINE } from "../offlineMode";
import { MoveRing } from "./MoveClock";
import { RING_SECS } from "../useMoveClock";

/** Leave below Next round, the same in every room. The round is over and
 *  recorded and the next has not started, so leaving costs nothing and goes
 *  at once; a practice game on this device ends with it, so that one still
 *  asks first. The modal dialog makes the HUD's own Leave control
 *  unreachable here. */
function RoundEndLeave({ ranked }: { ranked: boolean }) {
  const [asking, setAsking] = useState(false);
  return (
    <>
      <button
        type="button"
        className="btn subtle danger dialog-leave-btn"
        onClick={() => (OFFLINE ? setAsking(true) : conn.send({ type: "leave_room" }))}
      >
        Leave game
      </button>
      {asking ? (
        <LeaveAlert ranked={ranked} practice betweenRounds
                    onKeep={() => setAsking(false)} onLeft={() => setAsking(false)} />
      ) : null}
    </>
  );
}

interface RoundEndModalProps {
  state: GameState;
  result: RoundResult;
  /** Seconds left on your move timer for Next (ranked tables), else null. */
  clock?: number | null;
}

/** Name the actual players, not the seat numbers: "Blue team (seats 0 & 2)"
 *  makes you work out who that was, and "you" should be obvious. */
function teamName(team: 0 | 1, state?: GameState): string {
  const colour = team === 0 ? "Blue" : "Orange";
  const members = teamMembers(team, state);
  return members ? `${colour} team (${members})` : `${colour} team`;
}

/** "You & Bot 2": the team's players, you first; empty when unknown. */
function teamMembers(team: 0 | 1, state?: GameState): string {
  if (!state) return "";
  return state.players
    .filter((p) => p.team === team)
    .sort((a, b) => Number(b.seat === state.you) - Number(a.seat === state.you) || a.seat - b.seat)
    .map((p) => (p.seat === state.you ? "You" : p.name))
    .join(" & ");
}

/** "Blue team · You & Bot 2 win the round"; the members take a plural verb,
 *  and phones drop the colour prefix (the title is already in team colour). */
function TeamTitle({ team, state, what }: { team: 0 | 1; state: GameState; what: string }) {
  const colour = team === 0 ? "Blue" : "Orange";
  const members = teamMembers(team, state);
  if (!members) return <>{colour} team wins {what}</>;
  return <><span className="title-team">{colour} team · </span>{members} win {what}</>;
}

function signedDelta(delta: number): string {
  if (delta > 0) return `▲ +${delta}`;
  if (delta < 0) return `▼ −${Math.abs(delta)}`;
  return "±0";
}

/** The viewer's own rating after the round (the server sends it only to a
 *  signed-in seat, once the round is stored); a guest at a deployment with
 *  sign-in gets Sign in to be ranked in its place. ``total`` shows the whole
 *  game's change where a game was won. An unranked room shows neither. */
export function RatingLine({ result, total, ranked }: { result: RoundResult; total: boolean; ranked: boolean }) {
  const account = useAuth();
  const [signingIn, setSigningIn] = useState(false);
  const rating = result.rating;
  if (!ranked) return null;
  if (result.unranked === "joined") {
    return <div className="rating-line rating-unranked"><span>Unranked · joined mid-round</span></div>;
  }
  if (rating) {
    const game = total && rating.game_delta !== undefined ? rating.game_delta : null;
    const tone = (d: number) => (d > 0 ? "delta-up" : d < 0 ? "delta-dn" : "delta-flat");
    return (
      <div className="rating-line">
        <span>Your rating <b>{rating.rating}</b></span>
        <span className="rating-deltas">
          <span className={`rating-delta ${tone(rating.delta)}`}>{signedDelta(rating.delta)}</span>
          {game !== null ? (
            <span className={`rating-game ${tone(game)}`}>
              {game > 0 ? "+" : game < 0 ? "−" : "±"}{Math.abs(game)} this game
            </span>
          ) : null}
        </span>
      </div>
    );
  }
  if (account.status !== "out" || !account.clientId) return null;
  return (
    <div className="rating-guest">
      {signingIn ? (
        <GoogleSignIn clientId={account.clientId} />
      ) : (
        <button className="rating-signin" onClick={() => setSigningIn(true)}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
               strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M8 4h8v5a4 4 0 0 1-8 0z" />
            <path d="M8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4M12 13v4M9 20h6" />
          </svg>
          Sign in to be ranked
        </button>
      )}
    </div>
  );
}

/** Card points: 5s are worth 5, 10s and kings 10, everything else 0. */
function cardPoints(code: string): number {
  const rank = code.slice(1);
  if (rank === "5") return 5;
  if (rank === "10" || rank === "K") return 10;
  return 0;
}

export default function RoundEndModal({ state, result, clock = null }: RoundEndModalProps) {
  const titleId = useId();
  const ranked = !!(state.matched || state.ranked);
  const nextBankerName =
    state.players.find((p) => p.seat === result.next_banker)?.name ?? `Seat ${result.next_banker}`;
  // attacker_points is the final total (kitty bonus already included);
  // kitty_points is the kitty portion of that total.
  const total = result.attacker_points;
  const trickPoints = result.attacker_points - result.kitty_points;
  // kitty_cards are the 8 cards the banker buried (the server sends rnd.buried).
  const buriedPoints = result.kitty_cards.reduce((sum, code) => sum + cardPoints(code), 0);
  const bankerName =
    state.banker === null
      ? null
      : state.banker === state.you
      ? "you"
      : state.players.find((p) => p.seat === state.banker)?.name ?? `Seat ${state.banker}`;

  if (result.game_over) {
    return (
      <ResultDialog titleId={titleId}>
        <div className="panel modal victory">
          <div className="victory-crown">👑</div>
          <h2 id={titleId} tabIndex={-1} className={`victory-title team${result.winner_team}`}>
            <TeamTitle team={result.winner_team} state={state} what="the game!" />
          </h2>
          <p className="victory-sub">
            Final levels — Blue: {result.new_levels[0]} · Orange: {result.new_levels[1]}
          </p>
          <RatingLine result={result} total ranked={ranked} />
          <button
            className="btn primary big"
            onClick={() => conn.leaveToLobby()}
          >
            Back to lobby
          </button>
        </div>
      </ResultDialog>
    );
  }

  const levels = result.level_change === 1 ? "level" : "levels";
  return (
    <ResultDialog titleId={titleId}>
      <div className="panel modal">
        <h2 id={titleId} tabIndex={-1} className={`modal-title team${result.winner_team}`}>
          <TeamTitle team={result.winner_team} state={state} what="the round" />
        </h2>

        {/* the outcome first; how it was scored waits behind Details */}
        <div className="result-headline">
          <span className={`result-change team${result.winner_team}`}>
            {result.point_scored ? "Game won" : `+${result.level_change} ${levels}`}
          </span>
          <span className="result-levels">
            {result.point_scored ? "Levels restart at " : "Now "}
            <span className="team-dot t0" /> {result.new_levels[0]}
            <span className="team-dot t1" /> {result.new_levels[1]}
          </span>
          <span className="result-score">Attackers {total} of 80</span>
        </div>

        <RatingLine result={result} total={result.point_scored} ranked={ranked} />

        <details className="result-details">
          <summary>Details</summary>
          {result.kitty_cards.length > 0 && (
            <div className="kitty-reveal">
              <div className="kitty-reveal-label">
                {bankerName ? `Buried by ${bankerName}` : "Buried"} · {buriedPoints} pts
              </div>
              <div className="kitty-cards">
                {result.kitty_cards.map((code, i) => (
                  <Card key={i} code={code} />
                ))}
              </div>
            </div>
          )}

          <div className="result-grid">
            <span className="result-label">Trick points</span>
            <span className="result-value">{trickPoints}</span>

            {result.kitty_points > 0 && (
              <>
                <span className="result-label">Kitty bonus</span>
                <span className="result-value">+{result.kitty_points}</span>
              </>
            )}

            <span className="result-label total">Total</span>
            <span className="result-value total">
              {total} <span className="result-note">(80 needed)</span>
            </span>

            <span className="result-label">
              {result.point_scored ? "Result" : "Level change"}
            </span>
            <span className="result-value">
              {result.point_scored
                ? `${teamName(result.winner_team, state)} wins the game`
                : `+${result.level_change}`}
            </span>

            {result.point_scored ? (
              <>
                <span className="result-label">Games won</span>
                <span className="result-value">
                  <span className="team-dot t0" /> {result.games_won[0]}
                  <span className="team-dot t1" style={{ marginLeft: 12 }} />{" "}
                  {result.games_won[1]}
                </span>
              </>
            ) : null}

            <span className="result-label">
              {result.point_scored ? "Levels restart at" : "New levels"}
            </span>
            <span className="result-value">
              <span className="team-dot t0" /> {result.new_levels[0]}
              <span className="team-dot t1" style={{ marginLeft: 12 }} /> {result.new_levels[1]}
            </span>

            <span className="result-label">Next banker</span>
            <span className="result-value">{nextBankerName}</span>
          </div>

          <p className="result-verdict">
            {result.point_scored
              ? `${teamName(result.winner_team, state)} held Ace and wins the game — levels restart at ${result.new_levels[0]} and play continues.`
              : total >= 80
              ? `Attackers reached ${total} of the 80 needed — ${teamName(result.winner_team, state)} goes up ${result.level_change} level${result.level_change === 1 ? "" : "s"}.`
              : `Attackers fell short with ${total} of the 80 needed — ${teamName(result.winner_team, state)} goes up ${result.level_change} level${result.level_change === 1 ? "" : "s"}.`}
          </p>
        </details>

        {(() => {
          // Everyone reviews the round at their own pace: the server only
          // advances once EVERY connected human has confirmed.
          // Only CONNECTED humans are counted — a player who drops during
          // the round-end screen is taken off the tally server-side too.
          const humans = state.players.filter((p) => !p.is_bot && p.connected);
          const ready = state.ready ?? [];
          const iAmReady = ready.includes(state.you);
          const waiting = humans.filter((p) => !ready.includes(p.seat));
          return (
            <>
              <button
                className={`btn primary big${!iAmReady && clock !== null && clock <= RING_SECS ? " clock-low" : ""}`}
                disabled={iAmReady}
                onClick={() => conn.send({ type: "next_round" })}
              >
                {iAmReady ? null : <MoveRing left={clock} />}
                {iAmReady ? "Waiting for others…" : "Next round"}
              </button>
              {humans.length > 1 && (
                <div className="ready-status">
                  {ready.length}/{humans.length} ready
                  {waiting.length > 0 && iAmReady && (
                    <> — waiting for {waiting.map((p) => p.name).join(", ")}</>
                  )}
                </div>
              )}
              <RoundEndLeave ranked={ranked} />
            </>
          );
        })()}
      </div>
    </ResultDialog>
  );
}
