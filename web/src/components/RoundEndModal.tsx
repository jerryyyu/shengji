import type { GameState, RoundResult } from "../protocol";
import { conn } from "../ws";
import Card from "./Card";
import { useId, useState } from "react";
import ResultDialog from "./ResultDialog";
import LeaveSheet from "./LeaveSheet";
import { OFFLINE } from "../offlineMode";
import { TimerRing } from "./MoveClock";
import { LOW_SECS, MOVE_SECS } from "../useMoveClock";
import { telemetry, useScreen } from "../telemetry";
import { myTeam, nextBankerText, pointsOf, roundLines, teamMembers, teamWord } from "../tableCopy";

/** Leave below Next round (Next game), the same in every room. It asks through the one
 *  leave sheet, like every other leave: the round is over and recorded, so
 *  the sheet says it is free; an offline game on this device ends with it.
 *  The modal dialog makes the HUD's own Leave control unreachable here. */
function RoundEndLeave({ ranked, guest }: { ranked: boolean; guest: boolean }) {
  const [asking, setAsking] = useState(false);
  return (
    <>
      <button
        type="button"
        className="btn subtle danger dialog-leave-btn"
        onClick={() => {
          telemetry.tap("round_end_leave");
          setAsking(true);
        }}
      >
        Leave game
      </button>
      {asking ? (
        <LeaveSheet context={{ kind: "game", ranked, guest, practice: OFFLINE, betweenRounds: true }}
                    onStay={() => setAsking(false)}
                    onLeave={() => { conn.send({ type: "leave_room" }); setAsking(false); }} />
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

/** Name the actual players, not seat numbers or a colour: "Us (You & Sam)". */
function teamName(team: 0 | 1, state: GameState): string {
  const members = teamMembers(team, state);
  const word = teamWord(team, state);
  return members ? `${word} (${members})` : word;
}

/** "You & Bot 2 win the round"; the members take a plural verb. */
function TeamTitle({ team, state, what, verb = "win" }: {
  team: 0 | 1; state: GameState; what: string; verb?: "win" | "lose";
}) {
  const members = teamMembers(team, state);
  if (!members) return <>{teamWord(team, state)} {verb} {what}</>;
  return <>{members} {verb} {what}</>;
}

/** The viewer's team when it lost the round, else null (a win, or a viewer
 *  with no seat). A loss names your own side, "You & Sam lose the round":
 *  the winners' names alone read as someone else's news. */
export function losingViewerTeam(state: GameState, winner: 0 | 1): 0 | 1 | null {
  const mine = state.players.find((p) => p.seat === state.you)?.team;
  return mine === undefined || mine === winner ? null : mine;
}

function signedDelta(delta: number): string {
  if (delta > 0) return `▲ +${delta}`;
  if (delta < 0) return `▼ −${Math.abs(delta)}`;
  return "±0";
}

/** The viewer's own rating after the round (the server sends it only to a
 *  signed-in seat, once the round is stored); a guest seat (the result's
 *  `unranked: "guest"` or the state's `guest`) gets "Guest". ``total`` shows the whole
 *  game's change where a game was won. An unranked room shows neither. */
export function RatingLine({ result, total, ranked, guest = false }: {
  result: RoundResult; total: boolean; ranked: boolean;
  /** The viewer sits as a guest (the state's `guest`). */
  guest?: boolean;
}) {
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
  // an account's rating may still be on its way; only a guest seat is told
  if (result.unranked !== "guest" && !guest) return null;
  return <div className="rating-line rating-unranked rating-guest-note"><span>Guest</span></div>;
}

export default function RoundEndModal({ state, result, clock = null }: RoundEndModalProps) {
  const titleId = useId();
  useScreen("round_end");
  const ranked = !!(state.matched || state.ranked);
  // attacker_points is the final total (kitty bonus already included);
  // kitty_points is the kitty portion of that total.
  const total = result.attacker_points;
  const trickPoints = result.attacker_points - result.kitty_points;
  // kitty_cards are the 8 cards the banker buried (the server sends rnd.buried).
  const buriedPoints = pointsOf(result.kitty_cards);
  const bankerName =
    state.banker === null
      ? null
      : state.banker === state.you
      ? "you"
      : state.players.find((p) => p.seat === state.banker)?.name ?? `Seat ${state.banker}`;

  const lostTeam = losingViewerTeam(state, result.winner_team);
  // A team that defends at Ace wins a game: a point on the games score, and
  // both teams' levels restart. The table goes on, so this is Next game.
  const gameWon = result.point_scored;
  const what = gameWon ? "the game" : "the round";
  const climb = result.level_change > 0
    ? `go up ${result.level_change} level${result.level_change === 1 ? "" : "s"}`
    : "take the deal with no level change";
  return (
    <ResultDialog titleId={titleId}>
      <div className={`panel modal${gameWon ? " game-won" : ""}`}>
        {gameWon ? <div className="game-won-crown" aria-hidden="true">👑</div> : null}
        <h2 id={titleId} tabIndex={-1} className={`modal-title team${lostTeam ?? result.winner_team}`}>
          {lostTeam !== null
            ? <TeamTitle team={lostTeam} state={state} what={what} verb="lose" />
            : <TeamTitle team={result.winner_team} state={state} what={what} />}
        </h2>

        {/* the outcome first, your team first and in words; how it was
            scored waits behind Details */}
        {gameWon ? (
          <div className="result-headline result-games">
            Games: Us {result.games_won[myTeam(state)]} · Them {result.games_won[1 - myTeam(state)]}
          </div>
        ) : (
        <div className="result-headline result-teams">
          <div className="result-team-lines">
            {roundLines(state, result).map((line) => (
              <div key={line.team} className={`result-team-line team${line.team}${line.won ? " gained" : ""}`}>
                <span className={`team-dot t${line.team}`} aria-hidden="true" />
                <b className="result-team-word">{line.word}</b>
                <span className="result-team-members">({line.members})</span>
                <span className="result-team-what">
                  {line.role ? `${line.role} · ` : ""}{line.outcome}
                </span>
              </div>
            ))}
          </div>
          <span className="result-levels">
            {result.point_scored ? "Levels restart at " : "Levels now "}
            Us {result.new_levels[myTeam(state)]} · Them {result.new_levels[1 - myTeam(state)]}
          </span>
          <span className="result-next-banker">{nextBankerText(state, result)}</span>
        </div>
        )}

        <RatingLine result={result} total={result.point_scored} ranked={ranked} guest={state.guest === true} />

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
                ? `${teamName(result.winner_team, state)} win the game`
                : result.level_change > 0 ? `+${result.level_change}` : "None"}
            </span>

            {result.point_scored ? (
              <>
                <span className="result-label">Games won</span>
                <span className="result-value">
                  Us {result.games_won[myTeam(state)]} · Them {result.games_won[1 - myTeam(state)]}
                </span>
              </>
            ) : null}

            <span className="result-label">
              {result.point_scored ? "Levels restart at" : "New levels"}
            </span>
            <span className="result-value">
              Us {result.new_levels[myTeam(state)]} · Them {result.new_levels[1 - myTeam(state)]}
            </span>

          </div>

          <p className="result-verdict">
            {result.point_scored
              ? `${teamName(result.winner_team, state)} held Ace and win the game — levels restart at ${result.new_levels[0]} and play continues.`
              : total >= 80
              ? `Attackers reached ${total} of the 80 needed — ${teamName(result.winner_team, state)} ${climb}.`
              : `Attackers fell short with ${total} of the 80 needed — ${teamName(result.winner_team, state)} ${climb}.`}
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
                className={`btn primary big${!iAmReady && clock !== null && clock <= LOW_SECS ? " clock-low" : ""}`}
                disabled={iAmReady}
                onClick={() => { telemetry.tap("next_round"); conn.send({ type: "next_round" }); }}
              >
                {iAmReady ? null : <TimerRing left={clock} total={MOVE_SECS} />}
                {iAmReady ? "Waiting for others…" : gameWon ? "Next game" : "Next round"}
              </button>
              {humans.length > 1 && (
                <div className="ready-status">
                  {ready.length}/{humans.length} ready
                  {waiting.length > 0 && iAmReady && (
                    <> — waiting for {waiting.map((p) => p.name).join(", ")}</>
                  )}
                </div>
              )}
              <RoundEndLeave ranked={ranked} guest={state.guest === true} />
            </>
          );
        })()}
      </div>
    </ResultDialog>
  );
}
