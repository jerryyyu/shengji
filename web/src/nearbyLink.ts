// The nearby table's link, as the HUD's dot shows it. It reads the same
// state as the connection pill and the move gate: a joiner is linked only
// while its socket is open, which a nearby socket is only once the host has
// answered its resume (NearbySocket), so the dot is never green while a move
// cannot go. The host is linked while every person's seat is connected.
import type { ConnStatus } from "./ws";

export type NearbyLink = "linked" | "reconnecting" | "lost";

export function nearbyLinkState(o: {
  /** This page hosts the table. */
  host: boolean;
  status: ConnStatus;
  /** The joiner's host window has passed: the end screen follows. */
  hostLeft: boolean;
  players: readonly { is_bot: boolean; connected: boolean }[];
}): NearbyLink {
  if (o.host) return o.players.some((p) => !p.is_bot && !p.connected) ? "reconnecting" : "linked";
  if (o.hostLeft) return "lost";
  return o.status === "open" ? "linked" : "reconnecting";
}

/** The dot's accessible name, in the connection pill's own words. */
export const NEARBY_LINK_LABEL: Record<NearbyLink, string> = {
  linked: "Connected",
  reconnecting: "Reconnecting…",
  lost: "The host left. The game is over.",
};
