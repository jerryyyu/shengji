// A guest's name, shared by the Play tab and the wide top bar's chip: the
// name they play under and whether its editor is open. What the guest keeps
// and the first random fill are written to storage (saveName), so a guest is
// called the same thing on every page load until they choose a name.

import { useSyncExternalStore } from "react";
import { getSavedName, saveName } from "./ws";

/** What a guest's identity line says: the one thing a guest lacks. */
export const GUEST_LINE = "Guest · not ranked";

export interface GuestNameView {
  name: string;
  editing: boolean;
}

class GuestNameStore {
  private view: GuestNameView = { name: "", editing: false };
  private listeners = new Set<() => void>();
  private loaded = false;

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  };

  getSnapshot = (): GuestNameView => {
    if (!this.loaded) this.load();
    return this.view;
  };

  private load(): void {
    this.loaded = true;
    let saved = "";
    try { saved = getSavedName(); } catch { /* storage refused: start empty */ }
    this.view = { name: saved, editing: false };
  }

  private set(next: Partial<GuestNameView>): void {
    this.view = { ...this.view, ...next };
    for (const fn of this.listeners) fn();
  }

  get name(): string {
    return this.getSnapshot().name;
  }

  setName(name: string): void {
    if (name !== this.view.name) this.set({ name });
  }

  /** A random name for a guest who has none, kept at once so the next page
   *  load shows the same one. */
  fill(name: string): void {
    this.setName(name);
    this.keep(name);
  }

  /** Remember the name for next time; an empty one is not kept. */
  keep(name: string): void {
    const trimmed = name.trim();
    if (!trimmed) return;
    try { saveName(trimmed); } catch { /* storage refused: memory only */ }
  }

  open(): void {
    this.set({ editing: true });
  }

  close(): void {
    this.set({ editing: false });
  }

  /** Test seam: forget everything, as a fresh page would. */
  reset(): void {
    this.loaded = false;
    this.view = { name: "", editing: false };
  }
}

export const guestName = new GuestNameStore();

export function useGuestName(): GuestNameView {
  return useSyncExternalStore(guestName.subscribe, guestName.getSnapshot, guestName.getSnapshot);
}
