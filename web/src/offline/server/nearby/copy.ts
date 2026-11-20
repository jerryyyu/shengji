// Every player-visible nearby string, in one place, so the copy rule and
// the flows map can list them as one exception. The UI shows them only while
// the nearby flag is on (flag.ts).

export const NEARBY_COPY = {
  /** The host's switch row on the offline table, label only. */
  switchLabel: "Nearby",
  tryAgain: "Try again",
  browsing: "Looking for the table…",
  /** The link is up and the table's seats are on their way. */
  connecting: "Connecting to the table…",
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
