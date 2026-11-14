/** The last kind of input on the page: "pointer" after a mouse, pen or touch
 *  press, "keyboard" after a key. A dialog that moves focus itself reads it to
 *  decide whether to paint a focus ring: one opened from a tap should not, one
 *  opened from the keyboard must. */
export type Modality = "pointer" | "keyboard";

let last: Modality = "keyboard";
let listening = false;

const onPointer = () => { last = "pointer"; };
const onKey = (e: KeyboardEvent) => {
  // a modifier on its own (Cmd held for a shortcut) says nothing about navigation
  if (e.metaKey || e.ctrlKey || e.altKey || e.key === "Shift" || e.key === "Meta"
      || e.key === "Control" || e.key === "Alt") return;
  last = "keyboard";
};

/** Starts tracking; safe to call more than once. */
export function trackInputModality(): void {
  if (listening || typeof document === "undefined") return;
  listening = true;
  document.addEventListener("pointerdown", onPointer, true);
  document.addEventListener("mousedown", onPointer, true);
  document.addEventListener("touchstart", onPointer, { capture: true, passive: true });
  document.addEventListener("keydown", onKey, true);
}

export function lastInputModality(): Modality {
  return last;
}
