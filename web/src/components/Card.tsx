import { memo } from "react";

export const SUIT_SYMBOL: Record<string, string> = {
  S: "♠",
  H: "♥",
  D: "♦",
  C: "♣",
};

export function isRedCode(code: string): boolean {
  if (code === "BJ") return true;
  if (code === "LJ") return false;
  return code[0] === "H" || code[0] === "D";
}

/** Human label for a card code, e.g. "H10" -> "♥10", "BJ" -> "Big Joker". */
export function codeLabel(code: string): string {
  if (code === "BJ") return "Big Joker";
  if (code === "LJ") return "Little Joker";
  return (SUIT_SYMBOL[code[0]] ?? code[0]) + code.slice(1);
}

const SUIT_NAME: Record<string, string> = { S: "spades", H: "hearts", D: "diamonds", C: "clubs" };
const RANK_NAME: Record<string, string> = { J: "Jack", Q: "Queen", K: "King", A: "Ace" };

/** What a screen reader says for a card code: "H10" -> "10 of hearts",
 *  "SA" -> "Ace of spades", "BJ" -> "Big joker". VoiceOver reads "♠3" as
 *  "black spade suit 3" and "BJ" letter by letter. */
export function spokenLabel(code: string): string {
  if (code === "BJ") return "Big joker";
  if (code === "LJ") return "Little joker";
  const rank = code.slice(1);
  return `${RANK_NAME[rank] ?? rank} of ${SUIT_NAME[code[0]] ?? code[0]}`;
}

/** Compact label for a card code, e.g. "H10" -> "♥10"; jokers stay "LJ"/"BJ". */
export function shortLabel(code: string): string {
  if (code === "BJ" || code === "LJ") return code;
  return (SUIT_SYMBOL[code[0]] ?? code[0]) + code.slice(1);
}

interface CardProps {
  /** Card code ("S2", "H10", "BJ"...). Omit for a face-down back. */
  code?: string;
  selected?: boolean;
  onClick?: () => void;
  className?: string;
}

function Card({ code, selected = false, onClick, className }: CardProps) {
  const Face = onClick ? "button" : "div";
  // a tappable card is a toggle button; any other face is one image, so its
  // corner and pip glyphs are not read out one by one
  const label = code ? spokenLabel(code) : undefined;
  const accessibility = onClick
    ? { type: "button" as const, "aria-pressed": selected, "aria-label": label }
    : { role: "img", "aria-label": label };
  const cls = (extra: string) =>
    ["card", extra, selected ? "selected" : "", onClick ? "clickable" : "", className ?? ""]
      .filter(Boolean)
      .join(" ");

  if (!code) {
    return <div className={cls("back")} aria-hidden="true" />;
  }

  if (code === "BJ" || code === "LJ") {
    const red = code === "BJ";
    return (
      <Face {...accessibility} className={cls(`joker ${red ? "red" : "black"}`)} onClick={onClick} title={codeLabel(code)}>
        <span className="joker-text" aria-hidden="true">JOKER</span>
        <span className="joker-star" aria-hidden="true">{red ? "★" : "☆"}</span>
      </Face>
    );
  }

  const suit = code[0];
  const rank = code.slice(1);
  const symbol = SUIT_SYMBOL[suit] ?? "?";
  const red = suit === "H" || suit === "D";

  return (
    <Face {...accessibility} className={cls(red ? "red" : "black")} onClick={onClick} title={codeLabel(code)}>
      <span className="corner tl" aria-hidden="true">
        <span className="corner-rank">{rank}</span>
        <span className="corner-suit">{symbol}</span>
      </span>
      <span className="pip" aria-hidden="true">{symbol}</span>
      <span className="corner br" aria-hidden="true">
        <span className="corner-rank">{rank}</span>
        <span className="corner-suit">{symbol}</span>
      </span>
    </Face>
  );
}

/** Memoized: a server state re-renders the whole table, but a card's look
 *  depends only on these props, so unchanged cards skip rendering. Callers
 *  must pass a stable onClick (see Hand) for that to hold. */
export default memo(Card);
