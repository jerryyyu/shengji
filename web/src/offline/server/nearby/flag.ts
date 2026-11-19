// The nearby feature flag. Off everywhere: nothing in the page reaches nearby
// play unless the flag is on AND the app binary says it was reviewed with the
// feature (the plugin's `capabilities().reviewed`), so the live site alone can
// never switch it on in a binary whose review did not cover it.

let forced: boolean | null = null;

/** Build-time switch; no build sets it yet. */
const BUILT_ON = import.meta.env.VITE_SHENGJI_NEARBY === "1";

/** Whether nearby play may be offered, given what the app binary reports. */
export function nearbyEnabled(binaryReviewed: boolean): boolean {
  if (forced !== null) return forced;
  return BUILT_ON && binaryReviewed;
}

/** Tests turn the flag on (or off) regardless of the build and the binary. */
export function setNearbyForTests(on: boolean | null): void {
  forced = on;
}
