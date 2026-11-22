import { useLayoutEffect, useSyncExternalStore } from "react";
import type { RefObject } from "react";

/** The open modal dialogs a page-level sheet can rise above. A dialog opened
 *  with showModal() sits in the browser's top layer and blocks everything
 *  outside it, so a sheet that opens over one is drawn inside the newest of
 *  them. The full-screen connection notice does not register: it stays above
 *  every sheet. */
let hosts: HTMLElement[] = [];
const listeners = new Set<() => void>();

function emit(): void {
  for (const l of listeners) l();
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => { listeners.delete(l); };
}

function top(): HTMLElement | null {
  return hosts.length > 0 ? hosts[hosts.length - 1] : null;
}

/** Registers the dialog in `ref` as a host while it is mounted. */
export function useModalHost(ref: RefObject<HTMLElement | null>): void {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    hosts = [...hosts, el];
    emit();
    return () => {
      hosts = hosts.filter((h) => h !== el);
      emit();
    };
  }, [ref]);
}

/** The newest open host dialog, or null when none is open. */
export function useTopModalHost(): HTMLElement | null {
  return useSyncExternalStore(subscribe, top, () => null);
}
