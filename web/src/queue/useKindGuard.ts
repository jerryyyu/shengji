import { useEffect, useState } from "react";
import type { PanelKind } from "./tableText";

/** After the panel changes kind its primary button waits this long, so a
 *  tap aimed at Join or Play never lands on an irrevocable Start. */
export const GUARD_MS = 700;

/** True for GUARD_MS after `kind` changes (not on first render). */
export function useKindGuard(kind: PanelKind): boolean {
  const [seen, setSeen] = useState<{ kind: PanelKind; at: number }>({ kind, at: 0 });
  const [, rerender] = useState(0);
  let current = seen;
  if (seen.kind !== kind) {
    current = { kind, at: Date.now() };
    setSeen(current);
  }
  const at = current.at;
  useEffect(() => {
    const left = at + GUARD_MS - Date.now();
    if (left <= 0) return;
    const t = window.setTimeout(() => rerender((n) => n + 1), left);
    return () => window.clearTimeout(t);
  }, [at]);
  return at + GUARD_MS > Date.now();
}
