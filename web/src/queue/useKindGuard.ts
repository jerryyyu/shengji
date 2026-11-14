import { useEffect, useState } from "react";
/** After the panel changes kind its primary button waits this long, so a
 *  tap aimed at Join or Play never lands on an irrevocable Start. */
export const GUARD_MS = 700;

/** True for GUARD_MS after `kind` changes (not on first render). `kind` is
 *  the panel's kind, or any key that names what its primary button does. */
export function useKindGuard(kind: string): boolean {
  const [seen, setSeen] = useState<{ kind: string; at: number }>({ kind, at: 0 });
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
