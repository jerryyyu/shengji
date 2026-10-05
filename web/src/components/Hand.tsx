import { memo } from "react";
import type { HandCard } from "../protocol";
import Card from "./Card";

interface HandProps {
  hand: HandCard[];
  selected: Set<number>;
  /** Whether cards can currently be toggled. */
  selectable: boolean;
  /** Must be stable across renders (Table passes a useCallback). */
  onToggle: (id: number) => void;
}

interface SlotProps {
  id: number;
  code: string;
  selected: boolean;
  onToggle: ((id: number) => void) | undefined;
}

/** One card in the hand. Props are primitives plus the stable onToggle, so a
 *  server update or a tap re-renders only the slots whose card or selection
 *  changed, not all 25. */
const HandSlot = memo(function HandSlot({ id, code, selected, onToggle }: SlotProps) {
  return (
    <div className="hand-slot">
      <Card code={code} selected={selected} onClick={onToggle ? () => onToggle(id) : undefined} />
    </div>
  );
});

export default function Hand({ hand, selected, selectable, onToggle }: HandProps) {
  if (hand.length === 0) return null;
  return (
    <div className={`hand${selectable ? " selectable" : ""}`}>
      {hand.map((c) => (
        <HandSlot key={c.id} id={c.id} code={c.code} selected={selected.has(c.id)}
                  onToggle={selectable ? onToggle : undefined} />
      ))}
    </div>
  );
}
