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

export default function Card({ code, selected = false, onClick, className }: CardProps) {
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
      <div className={cls(`joker ${red ? "red" : "black"}`)} onClick={onClick} title={codeLabel(code)}>
        <span className="joker-text">JOKER</span>
        <span className="joker-star">{red ? "★" : "☆"}</span>
      </div>
    );
  }

  const suit = code[0];
  const rank = code.slice(1);
  const symbol = SUIT_SYMBOL[suit] ?? "?";
  const red = suit === "H" || suit === "D";

  return (
    <div className={cls(red ? "red" : "black")} onClick={onClick} title={codeLabel(code)}>
      <span className="corner tl">
        <span className="corner-rank">{rank}</span>
        <span className="corner-suit">{symbol}</span>
      </span>
      <span className="pip">{symbol}</span>
      <span className="corner br">
        <span className="corner-rank">{rank}</span>
        <span className="corner-suit">{symbol}</span>
      </span>
    </div>
  );
}
