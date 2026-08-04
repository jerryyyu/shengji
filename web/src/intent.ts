/**
 * Connection intent: WHICH room this socket should be in, and why.
 *
 * Ownership used to be split — ws.ts read localStorage and rejoined on its
 * own, Lobby owned invites and manual actions, App rendered whatever arrived —
 * and the recent membership bugs all lived on those seams (Codex). This module
 * is the single decision, expressed as a pure function so it can be tested
 * without a socket, a DOM, or a server.
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
  if (i.savedRoom && i.savedName) {
    return {
      kind: "resume",
      room: i.savedRoom.toUpperCase(),
      name: i.savedName,
      token: i.savedToken ?? undefined,
    };
  }
  return { kind: "none" };
}

/** The join_room message an intent implies, or null when nothing should be
 *  sent. An invite WITHOUT a name is deliberately not auto-joined: the lobby
 *  prefills and focuses the name field instead, so a returning player is not
 *  thrown into a room before they can change their name. */
export function intentToJoin(intent: Intent): Record<string, unknown> | null {
  switch (intent.kind) {
    case "invite":
      return intent.name?.trim()
        ? { type: "join_room", room: intent.room, name: intent.name.trim() }
        : null;
    case "pending":
      return {
        type: "join_room", room: intent.room, name: intent.name,
        ...(intent.seat !== undefined ? { seat: intent.seat } : {}),
        ...(intent.token ? { token: intent.token } : {}),
      };
    case "resume":
      return {
        type: "join_room", room: intent.room, name: intent.name,
        ...(intent.token ? { token: intent.token } : {}),
      };
    default:
      return null;
  }
}
