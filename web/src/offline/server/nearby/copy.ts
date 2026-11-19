// Every player-visible nearby string, in one place, so the copy rule and
// the flows map can list them as one exception. Nothing renders these yet:
// the nearby UI is gated off (flag.ts).

export const NEARBY_COPY = {
  modeTag: "Nearby",
  browsing: "Looking for the table…",
  notFound: "No table nearby with that code",
  full: "That table is full",
  /** The joiner's line under the code box, before the system prompt. */
  explain: "This is a nearby table. Sheng Ji will ask to use your local network to find it.",
  /** After a denial; "Open Settings" is the link text. */
  denied: "Nearby tables need Local Network access.",
  openSettings: "Open Settings",
  wifiOff: "Turn on Wi-Fi to play nearby",
  versionMismatch: "Update the app to join this table",
  hostLeft: "The host left. The game is over.",
} as const;
