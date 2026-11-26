import { useLayoutEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import type { CSSProperties } from "react";
import type { GameState, LastTrick } from "../protocol";
import Card from "./Card";
import { displayName, useT } from "../i18n";
import { fitDetails } from "./roundEndFit";

/** The width the row has to fill, kept current through resizes and turns. */
function useContentWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const read = () => {
      const style = getComputedStyle(el);
      const pad = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);
      setWidth(Math.max(0, el.clientWidth - pad));
    };
    read();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

/** The round-end Details, in the ladder's place: the kitty's fan and each
 *  seat's play in the last trick as a fan, the player's name under it and
 *  the winner's outlined, all on one row whose card size and overlap come
 *  from the measured width and the counts (fitDetails); the bonus line,
 *  when the attackers took the last trick, one line across the panel under
 *  the row, the sum alone when the sentence would not fit on one line. */
export default function RoundEndDetails({ id, state, kitty, kittyPoints, bonus, hidden }: {
  id: string; state: GameState; kitty: string[]; kittyPoints: number;
  bonus: { full: string; short: string } | null; hidden: boolean;
}) {
  const t = useT();
  const [ref, width] = useContentWidth<HTMLDivElement>();
  // the sentence's one-line width, read from an unseen copy of it
  const probe = useRef<HTMLSpanElement | null>(null);
  const [short, setShort] = useState(false);
  useLayoutEffect(() => {
    const need = probe.current?.offsetWidth ?? 0;
    setShort(width > 0 && need > width);
  }, [width, bonus?.full]);
  const trick: LastTrick | null = state.last_trick;
  const perSeat = trick ? Math.max(0, ...trick.plays.map((p) => p.cards.length)) : 0;
  const fit = fitDetails({ width, kitty: kitty.length, seats: trick?.plays.length ?? 0, perSeat });
  const vars = { "--cw": `${fit.cw}px`, "--fit-step": `${fit.step}px`, "--fit-col": `${fit.col}px` } as CSSProperties;
  const nameOf = (seat: number) => {
    if (seat === state.you) return t("roundend.you");
    const p = state.players.find((x) => x.seat === seat);
    return p === undefined ? t("roundend.seat", { n: seat }) : displayName(p.name, p.is_bot);
  };
  return (
    <div id={id} ref={ref} className="round-end-details" style={vars}
         aria-hidden={hidden || undefined} inert={hidden || undefined}>
      {/* the two labels share one line over the row, each over its own fans */}
      <div className="round-end-heads">
        {kitty.length > 0 ? (
          <div className="round-end-col-label round-end-kitty-label">{t("roundend.kitty", { points: kittyPoints })}</div>
        ) : null}
        {trick ? (
          <div className="round-end-col-label round-end-trick-label">
            {trick.points > 0
              ? t("roundend.lastTrickPoints", { name: nameOf(trick.winner), points: trick.points })
              : t("roundend.lastTrick", { name: nameOf(trick.winner) })}
          </div>
        ) : null}
      </div>
      <div className="round-end-row">
        {kitty.length > 0 ? (
          <div className="round-end-col round-end-kitty" style={{ minWidth: `${fit.kittyWidth}px` }}>
            <div className="round-end-fan round-end-kitty-cards">
              {kitty.map((code, i) => <Card key={i} code={code} />)}
            </div>
          </div>
        ) : null}
        {trick ? (
          <div className="round-end-col round-end-last-trick">
            <ol className="round-end-plays">
              {trick.plays.map((play) => (
                <li key={play.seat} className={`round-end-play${play.seat === trick.winner ? " winner" : ""}`}>
                  <span className="round-end-fan round-end-play-cards">
                    {play.cards.map((code, i) => <Card key={i} code={code} />)}
                  </span>
                  <span className="round-end-play-who" title={nameOf(play.seat)}>{nameOf(play.seat)}</span>
                </li>
              ))}
            </ol>
          </div>
        ) : null}
      </div>
      {bonus ? (
        <>
          <div className="kitty-bonus">{short ? bonus.short : bonus.full}</div>
          <span ref={probe} className="kitty-bonus kitty-bonus-probe" aria-hidden="true">{bonus.full}</span>
        </>
      ) : null}
    </div>
  );
}
