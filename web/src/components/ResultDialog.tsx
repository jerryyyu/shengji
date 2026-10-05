import { useEffect, useRef, type ReactNode } from "react";

/** A round result must be acknowledged, not silently dismissed. Native modal
 * isolation keeps the underlying table out of the tab order and accessibility tree. */
export default function ResultDialog({ children, titleId }: { children: ReactNode; titleId: string }) {
  const ref = useRef<HTMLDialogElement>(null);
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
    onCancel={(event) => event.preventDefault()} onKeyDown={(event) => event.stopPropagation()}>
    {children}
  </dialog>;
}
