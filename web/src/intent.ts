/**
 * Connection intent: WHICH room this socket should be in, and why.
 *
 * This module is the single decision, expressed as a pure function so it can
 * be tested without a socket, a DOM, or a server.
 *
 * Precedence, highest first:
 *   1. invite URL          — an explicit link the user just followed
 *   2. pending user action  — create/join they triggered this session
 *   3. saved resume         — the room this browser was last in
 *
 * A pending action outranks the saved room because the user is acting NOW; the
 * saved room outranks nothing, it is only a fallback. An invite outranks even
 * a pending action because following a link is the most recent explicit intent.
 */

import { CODE_LEN } from "./codes";
import type { ClientMsg } from "./protocol";

export type Intent =
  | { kind: "invite"; room: string; name?: string }
  | { kind: "pending"; room: string; name: string; seat?: number; token?: string }
  | { kind: "resume"; room: string; name: string; token?: string }
  | { kind: "none" };

export interface IntentInputs {
  /** ?room= / ?name= from the invite link, if any. */
  invite?: { room: string; name?: string } | null;
  /** An explicit create/join the user started but that has not landed yet. */
  pending?: { room: string; name: string; seat?: number; token?: string } | null;
  savedRoom?: string | null;
  savedName?: string | null;
  savedToken?: string | null;
}

export function decideIntent(i: IntentInputs): Intent {
  const invite = i.invite;
  if (invite?.room && invite.room.length === 4) {
    return { kind: "invite", room: invite.room.toUpperCase(), name: invite.name };
  }
  if (i.pending?.room && i.pending.name) {
    return { kind: "pending", ...i.pending, room: i.pending.room.toUpperCase() };
  }
  // only a game-server code is resumed: a longer one (a nearby table's,
  // which is never saved) is not sent to the game server
  if (i.savedRoom && i.savedRoom.length === CODE_LEN && i.savedName) {
    return {
      kind: "resume",
      room: i.savedRoom.toUpperCase(),
      name: i.savedName,
      token: i.savedToken ?? undefined,
    };
  }
  return { kind: "none" };
}

/** The table_join an intent implies, or null when nothing should be sent.
 *  Each expects a room, so a room that has gone answers room_not_found,
 *  which ends it on the page. An invite WITHOUT a name is deliberately not
 *  auto-joined: the lobby prefills and focuses the name field instead, so a
 *  returning player is not thrown into a room before they can change their
 *  name. */
export function intentToJoin(intent: Intent): Extract<ClientMsg, { type: "table_join" }> | null {
  switch (intent.kind) {
    case "invite":
      return intent.name?.trim()
        ? { type: "table_join", code: intent.room, name: intent.name.trim(), expect: "room" }
        : null;
    case "pending":
      return {
        type: "table_join", code: intent.room, name: intent.name, expect: "room",
        ...(intent.seat !== undefined ? { seat: intent.seat } : {}),
        ...(intent.token ? { token: intent.token } : {}),
      };
    case "resume":
      return {
        type: "table_join", code: intent.room, name: intent.name, expect: "room",
        ...(intent.token ? { token: intent.token } : {}),
      };
    default:
      return null;
  }
}
