import { useEffect, useRef, type ReactNode } from "react";
import { useModalHost } from "../modalHosts";

/** A round result must be acknowledged, not silently dismissed. Native modal
 * isolation keeps the underlying table out of the tab order and accessibility tree.
 * `onDismiss` (a watcher's card, which acknowledges nothing): a tap on the
 * backdrop outside the card, or Escape, closes it. */
export default function ResultDialog({ children, titleId, onDismiss }: {
  children: ReactNode; titleId: string; onDismiss?: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useModalHost(ref);
  useEffect(() => {
    const dialog = ref.current!;
    const previous = document.activeElement;
    dialog.showModal();
    dialog.querySelector<HTMLElement>("h2")?.focus();
    return () => {
      dialog.close();
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);
  return <dialog ref={ref} className="modal-backdrop" aria-labelledby={titleId}
    onCancel={(event) => { event.preventDefault(); onDismiss?.(); }}
    onClick={onDismiss ? (event) => { if (event.target === event.currentTarget) onDismiss(); } : undefined}
    onKeyDown={(event) => event.stopPropagation()}>
    {children}
  </dialog>;
}
