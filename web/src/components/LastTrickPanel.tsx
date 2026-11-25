import type { GameState, LastTrick } from "../protocol";
import { shortLabel } from "./Card";
import { displayName, useT } from "../i18n";

/** The previous trick, reopened: each play in order with who made it, the
 *  winner and the points it took. It stays until dismissed, so a newcomer can
 *  read why a trick went the way it did. */
export default function LastTrickPanel({ state, trick, onClose }: {
  state: GameState; trick: LastTrick; onClose: () => void;
}) {
  const t = useT();
  const nameOf = (seat: number) => {
    if (seat === state.you) return t("common.you");
    const p = state.players.find((x) => x.seat === seat);
    return p ? displayName(p.name, p.is_bot) : t("table.seatN", { n: seat });
  };
  const mine = trick.winner === state.you;
  const sum = trick.points > 0
    ? t(mine ? "table.lastYouWinPts" : "table.lastWinsPts", { name: nameOf(trick.winner), points: trick.points })
    : t(mine ? "table.lastYouWin" : "table.lastWins", { name: nameOf(trick.winner) });
  return (
    <div className="last-trick-panel" role="dialog" aria-label={t("table.lastTrick")}>
      <div className="last-trick-head">
        <b>{t("table.lastTrick")}</b>
        <span className="last-trick-sum">{sum}</span>
        <button className="last-trick-close" onClick={onClose} aria-label={t("table.closeLastTrick")}>×</button>
      </div>
      <ol className="last-trick-plays">
        {trick.plays.map((play) => (
          <li key={play.seat} className={`last-trick-row team${play.seat % 2}${play.seat === trick.winner ? " winner" : ""}`}>
            <span className="last-trick-who">
              {nameOf(play.seat)}
              {play.seat === trick.leader ? <span className="last-trick-tag">{t("table.leadTag")}</span> : null}
            </span>
            <span className="last-trick-cards">
              {play.cards.map((code, i) => (
                <span key={i} className={`last-trick-card${/^[HD]/.test(code) || code === "BJ" ? " red" : ""}`}>
                  {shortLabel(code)}
                </span>
              ))}
            </span>
            {play.seat === trick.winner ? <span className="last-trick-tag win">{t("table.winsTag")}</span> : <span />}
          </li>
        ))}
      </ol>
    </div>
  );
}
