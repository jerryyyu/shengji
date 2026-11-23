// A guest's name, shared by the Play tab and the wide top bar's chip: the
// name they play under and whether its editor is open. What the guest keeps
// and the first random fill are written to storage (saveName), so a guest is
// called the same thing on every page load until they choose a name.
// Next to the name, storage says whether the guest chose it ("1": typed in
// the name field) or the random fill gave it ("0"); a name saved before
// that mark existed has none.

import { useSyncExternalStore } from "react";
import { NAME_ADJECTIVES, NAME_NOUNS } from "./randomName";
import { telemetry, type SigninFrom } from "./telemetry";
import { getSavedName, saveName } from "./ws";

/** What a guest's identity line says, where an account shows its rating. */
export const GUEST_LINE = "Guest";

/** Storage key of the chosen-name mark kept beside `shengji.name`. */
export const NAME_CHOSEN_KEY = "shengji.nameChosen";

function readChosenMark(): string | null {
  try { return localStorage.getItem(NAME_CHOSEN_KEY); } catch { return null; }
}

function writeChosenMark(chosen: boolean): void {
  try { localStorage.setItem(NAME_CHOSEN_KEY, chosen ? "1" : "0"); } catch { /* storage refused */ }
}

export interface GuestNameView {
  name: string;
  editing: boolean;
}

class GuestNameStore {
  private view: GuestNameView = { name: "", editing: false };
  private listeners = new Set<() => void>();
  private loaded = false;
  // the name in view was typed by the guest since it loaded or was filled
  private typed = false;

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
    this.typed = false;
  }

  private set(next: Partial<GuestNameView>): void {
    this.view = { ...this.view, ...next };
    for (const fn of this.listeners) fn();
  }

  get name(): string {
    return this.getSnapshot().name;
  }

  /** The guest's own edit of the name field: a name they chose. */
  setName(name: string): void {
    this.getSnapshot();
    this.typed = true;
    if (name !== this.view.name) this.set({ name });
  }

  /** A random name for a guest who has none, kept at once so the next page
   *  load shows the same one, marked as not chosen. */
  fill(name: string): void {
    this.getSnapshot();
    this.typed = false;
    if (name !== this.view.name) this.set({ name });
    this.keep(name);
    writeChosenMark(false);
  }

  /** Remember the name for next time; an empty one is not kept. A name the
   *  guest typed is marked chosen; any other keeps its mark. */
  keep(name: string): void {
    const trimmed = name.trim();
    if (!trimmed) return;
    try { saveName(trimmed); } catch { /* storage refused: memory only */ }
    if (this.typed) writeChosenMark(true);
  }

  /** Open the identity sheet; `from` names the entry point for telemetry. */
  open(from?: SigninFrom): void {
    if (from) telemetry.signinOpen(from);
    this.set({ editing: true });
  }

  close(): void {
    this.set({ editing: false });
  }

  /** Test seam: forget everything, as a fresh page would. */
  reset(): void {
    this.loaded = false;
    this.typed = false;
    this.view = { name: "", editing: false };
  }
}

export const guestName = new GuestNameStore();

export function useGuestName(): GuestNameView {
  return useSyncExternalStore(guestName.subscribe, guestName.getSnapshot, guestName.getSnapshot);
}

/** Whether `name` is one the random fill (or its dice) could have given. */
function isRandomName(name: string): boolean {
  const [adjective, noun, ...rest] = name.split(" ");
  return rest.length === 0 && (NAME_ADJECTIVES as readonly string[]).includes(adjective)
    && (NAME_NOUNS as readonly string[]).includes(noun ?? "");
}

/** The name this guest chose, for a new device account to keep: the one
 *  kept in storage when its mark says the guest chose it, or null when there
 *  is none, storage is refused, or the random fill gave it (the server draws
 *  its own). A name with no mark, saved before the mark existed, counts as
 *  chosen unless the random fill could have given it. */
export function chosenGuestName(): string | null {
  let saved = "";
  try { saved = getSavedName().trim(); } catch { return null; }
  if (!saved) return null;
  const mark = readChosenMark();
  if (mark === "1") return saved;
  if (mark === "0") return null;
  return isRandomName(saved) ? null : saved;
}
