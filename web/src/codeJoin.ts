// Every join box and the `?code=` link take a room code or a pair code: the
// code is looked up first (PROTOCOL.md "Codes"), then the room flow (peek,
// seat picker, join_room) or the pair flow (party_join, which needs sign-in)
// runs as it always has.

import { useSyncExternalStore } from "react";
import { auth } from "./auth";
import { CODE_LEN, NO_CODE, normalizeCode } from "./codes";
import { openTab } from "./home/route";
import type { ServerMsg } from "./protocol";
import { queue } from "./queue/store";
import type { ConnStatus } from "./ws";
import { conn } from "./ws";

/** Where a lookup started: the Play box, the pair sheet's box, or a link. */
export type CodeFrom = "play" | "pair" | "link";

export interface CodeView {
  /** The lookup waiting for its code_kind. */
  pending: { code: string; from: CodeFrom } | null;
  /** A room code for the Play screen to open; it may not be mounted yet. */
  room: { code: string; from: CodeFrom; at: number } | null;
  /** Why the Play box's (or a link's) code went nowhere. */
  playError: string | null;
}

const EMPTY: CodeView = { pending: null, room: null, playError: null };

/** Drop one query parameter from the address, keeping the rest. */
function dropParam(name: string): void {
  const params = new URLSearchParams(window.location.search);
  if (!params.has(name)) return;
  params.delete(name);
  const rest = params.toString();
  window.history.replaceState(window.history.state, "",
    `${window.location.pathname}${rest ? `?${rest}` : ""}${window.location.hash}`);
}

export class CodeStore {
  view: CodeView = EMPTY;
  private listeners = new Set<() => void>();
  private attached = false;
  /** The `?code=` link is looked up once per page, on the first open socket. */
  private linkTaken = false;
  /** Codes of cancelled lookups whose answers are still on the way. The
   *  server answers lookups in the order they were sent, one reply each, so
   *  the oldest of these is the next answer to drop. */
  private stale: string[] = [];

  attach(): void {
    if (this.attached) return;
    this.attached = true;
    // a test may stand in a partial socket
    conn.subscribe?.((m) => this.onMessage(m));
    conn.subscribeStatus?.((s) => this.onStatus(s));
    // Dismissing the pair sheet (Cancel, the scrim, Escape, a drag) cancels
    // its lookup. The room handoff clears the lookup before it closes the
    // sheet, so it is not a dismissal.
    queue.subscribe?.(() => {
      if (this.view.pending?.from === "pair" && queue.view.sheet !== "party") this.cancel();
    });
  }

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  };

  getSnapshot = (): CodeView => this.view;

  private set(next: Partial<CodeView>): void {
    this.view = { ...this.view, ...next };
    for (const fn of this.listeners) fn();
  }

  private onStatus(s: ConnStatus): void {
    // The answer, if any, died with the socket. A link's lookup is asked
    // again on the next open socket; one that was answered is not.
    if (s !== "open") {
      this.stale = [];
      const p = this.view.pending;
      if (p) {
        if (p.from === "link") this.linkTaken = false;
        this.set({ pending: null });
      }
      return;
    }
    if (this.linkTaken) return;
    this.linkTaken = true;
    const code = new URLSearchParams(window.location.search).get("code");
    if (code) this.lookup(code, "link");
  }

  /** Ask what `raw` names; false when it is not a whole code or the socket is down. */
  lookup(raw: string, from: CodeFrom): boolean {
    const code = normalizeCode(raw);
    if (code.length !== CODE_LEN) return false;
    if (!conn.send({ type: "code_lookup", code })) return false;
    // one lookup at a time: a newer one replaces any still waiting
    if (this.view.pending) this.stale.push(this.view.pending.code);
    this.set({ pending: { code, from }, ...(from === "pair" ? {} : { playError: null }) });
    if (from === "pair") queue.showPartyError(null);
    return true;
  }

  /** Drop the waiting lookup: its answer, when it comes, does nothing. */
  cancel(): void {
    const p = this.view.pending;
    if (!p) return;
    this.stale.push(p.code);
    this.set({ pending: null });
  }

  /** The Play screen takes the room code it is about to open. */
  takeRoom(): CodeView["room"] {
    const r = this.view.room;
    if (r) this.set({ room: null });
    return r;
  }

  clearPlayError(): void {
    if (this.view.playError) this.set({ playError: null });
  }

  private onMessage(msg: ServerMsg): void {
    // rate_limited is the one refusal code_lookup has; any other error
    // answers some other request and leaves the lookup waiting.
    const answer = (msg.type === "code_kind" || (msg.type === "error" && msg.code === "rate_limited"));
    if (answer && this.stale.length > 0
        && (msg.type === "error" || msg.code === this.stale[0])) {
      this.stale.shift();
      return;
    }
    const p = this.view.pending;
    if (!p) return;
    if (msg.type === "error") {
      if (msg.code !== "rate_limited") return;
      this.set({ pending: null });
      if (p.from === "pair") queue.showPartyError(msg.message);
      else this.set({ playError: msg.message });
      return;
    }
    if (msg.type !== "code_kind" || msg.code !== p.code) return;
    this.set({ pending: null });
    if (p.from === "link" && msg.kind !== "room") dropParam("code");
    if (msg.kind === "room") {
      if (p.from === "pair") {
        queue.closeSheet();
        openTab("play");
      }
      this.set({ room: { code: p.code, from: p.from, at: Date.now() } });
    } else if (msg.kind === "party") {
      this.party(p.code, p.from);
    } else if (p.from === "pair") {
      queue.showPartyError(NO_CODE);
    } else {
      this.set({ playError: NO_CODE });
    }
  }

  /** A pair code: join it when signed in; a guest is asked to sign in and
   *  comes back to the pair sheet with the code filled in. A link only
   *  fills the sheet in, as `?party=` always has. */
  private party(code: string, from: CodeFrom): void {
    const status = auth.state?.status;
    if (status === "in" && from !== "link") {
      queue.joinParty(code);
      return;
    }
    queue.setJoinCode(code);
    if (status === "in") {
      queue.openSheet("party");
    } else {
      // QueueLayer opens the pair sheet once the account is signed in
      queue.findAfterSignIn = true;
      if (status === "out" || status === "off") queue.openSheet("guest");
    }
  }

  /** Test seam: forget everything, as a fresh page would. */
  reset(): void {
    this.view = EMPTY;
    this.linkTaken = false;
    this.stale = [];
  }
}

export const codes = new CodeStore();
codes.attach();

export function useCodes(): CodeView {
  return useSyncExternalStore(codes.subscribe, codes.getSnapshot, codes.getSnapshot);
}
