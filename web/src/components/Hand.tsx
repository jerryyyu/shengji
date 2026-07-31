import type { HandCard } from "../protocol";
import Card from "./Card";

interface HandProps {
  hand: HandCard[];
  selected: Set<number>;
  /** Whether cards can currently be toggled. */
  selectable: boolean;
  onToggle: (id: number) => void;
}

export default function Hand({ hand, selected, selectable, onToggle }: HandProps) {
  if (hand.length === 0) return null;
  return (
    <div className={`hand${selectable ? " selectable" : ""}`}>
      {hand.map((c) => (
        <div key={c.id} className="hand-slot">
          <Card
            code={c.code}
            width={72}
            selected={selected.has(c.id)}
            onClick={selectable ? () => onToggle(c.id) : undefined}
          />
        </div>
      ))}
    </div>
  );
}
