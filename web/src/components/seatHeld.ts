import { useCallback, useEffect, useRef } from "react";

/** Keys that alone are no sign of a person at the device. */
const NOT_A_PRESS = new Set(["Shift", "Control", "Alt", "Meta", "CapsLock", "Fn"]);

/** While `active`, any tap or key press anywhere counts as back: `onBack`
 *  runs once per hold. Returns the same once-only back for a button, which a
 *  screen reader can press with a click and no tap or key. */
export function useAnyTapIsBack(active: boolean, onBack: () => void): () => void {
  const latest = useRef(onBack);
  const done = useRef(false);
  useEffect(() => { latest.current = onBack; });
  const back = useCallback(() => {
    if (done.current) return;
    done.current = true;
    latest.current();
  }, []);
  useEffect(() => {
    done.current = false;
    if (!active) return;
    const press = (e: Event) => {
      if (e instanceof KeyboardEvent && NOT_A_PRESS.has(e.key)) return;
      back();
    };
    document.addEventListener("pointerdown", press, true);
    document.addEventListener("keydown", press, true);
    return () => {
      document.removeEventListener("pointerdown", press, true);
      document.removeEventListener("keydown", press, true);
    };
  }, [active, back]);
  return back;
}
