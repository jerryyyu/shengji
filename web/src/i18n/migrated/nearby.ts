// The files whose visible copy comes from messages/nearby.ts; noHardcodedCopy.test.ts
// checks each one for English left in JSX or a copy field.
// nearbyUi.tsx is not listed: its test-tool rows (Copy log, Autoplay…) stay
// English, and nativeConstants.test.ts reads their literal spans.
export const FILES: string[] = [
  "components/OfflinePlay.tsx",
  "components/offlineGame.ts",
  "offline/server/nearby/copy.ts",
  "nearbyGate.ts",
  "nearbyJoin.ts",
  "nearbySession.ts",
  "offlineMode.ts",
];
