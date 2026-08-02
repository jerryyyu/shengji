import type { GameState, RoundResult } from "../protocol";
import { clearSavedRoom, conn } from "../ws";
import Card from "./Card";

interface RoundEndModalProps {
  state: GameState;
  result: RoundResult;
}

function teamName(team: 0 | 1): string {
  return team === 0 ? "Blue team (seats 0 & 2)" : "Orange team (seats 1 & 3)";
}

export default function RoundEndModal({ state, result }: RoundEndModalProps) {
  const nextBankerName =
    state.players.find((p) => p.seat === result.next_banker)?.name ?? `Seat ${result.next_banker}`;
  // attacker_points is the final total (kitty bonus already included);
  // kitty_points is the kitty portion of that total.
  const total = result.attacker_points;
  const trickPoints = result.attacker_points - result.kitty_points;

  if (result.game_over) {
    return (
      <div className="modal-backdrop">
        <div className="panel modal victory">
          <div className="victory-crown">👑</div>
          <h2 className={`victory-title team${result.winner_team}`}>
            {teamName(result.winner_team)} wins the game!
          </h2>
          <p className="victory-sub">
            Final levels — Blue: {result.new_levels[0]} · Orange: {result.new_levels[1]}
          </p>
          <button
            className="btn primary big"
            onClick={() => {
              clearSavedRoom();
              location.reload();
            }}
          >
            Back to lobby
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="modal-backdrop">
      <div className="panel modal">
        <h2 className={`modal-title team${result.winner_team}`}>{teamName(result.winner_team)} wins the round</h2>

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

          <span className="result-label">Level change</span>
          <span className="result-value">+{result.level_change}</span>

          <span className="result-label">New levels</span>
          <span className="result-value">
            <span className="team-dot t0" /> {result.new_levels[0]}
            <span className="team-dot t1" style={{ marginLeft: 12 }} /> {result.new_levels[1]}
          </span>

          <span className="result-label">Next banker</span>
          <span className="result-value">{nextBankerName}</span>
        </div>

        <p className="result-verdict">
          {total >= 80
            ? `Attackers reached ${total} of the 80 needed — ${teamName(result.winner_team)} goes up ${result.level_change} level${result.level_change === 1 ? "" : "s"}.`
            : `Attackers fell short with ${total} of the 80 needed — ${teamName(result.winner_team)} goes up ${result.level_change} level${result.level_change === 1 ? "" : "s"}.`}
        </p>

        <div className="kitty-reveal">
          <div className="kitty-reveal-label">Kitty</div>
          <div className="kitty-cards">
            {result.kitty_cards.map((code, i) => (
              <Card key={i} code={code} />
            ))}
          </div>
        </div>

        <button className="btn primary big" onClick={() => conn.send({ type: "next_round" })}>
          Next round
        </button>
      </div>
    </div>
  );
}
