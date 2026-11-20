// The nearby feature flag. Off everywhere: nothing in the page reaches nearby
// play unless the flag is built on AND the app binary allows it (the plugin's
// `capabilities()`: reviewed with the feature, or a Debug build for the device
// test), so the live site alone can never switch it on in a binary whose
// review did not cover it. No shipped config builds the flag on.

let forced: boolean | null = null;

/** Build-time switch: VITE_SHENGJI_NEARBY=1, set only by the device test's
 *  Debug build script. */
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
