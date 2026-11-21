// The nearby feature flag, decided at run time by the app binary alone: the
// plugin's `capabilities()` says the binary was reviewed with nearby play, is
// the Beta build (TestFlight internal testing only), or is a Debug build for
// the device test. The live site carries the nearby code, but it never runs
// in a browser or in an App Store binary, which reports none of the three.

let forced: boolean | null = null;

/** What the plugin reported, as far as nearby play needs it. */
export interface NearbyCapabilities {
  reviewed?: unknown;
  beta?: unknown;
  debug?: unknown;
  logFile?: unknown;
}

/** Whether nearby play may be offered, given what the app binary reports. */
export function nearbyEnabled(c: NearbyCapabilities | null): boolean {
  if (forced !== null) return forced;
  return c !== null && (c.reviewed === true || c.beta === true || c.debug === true);
}

/** Tests turn the flag on (or off) regardless of the binary. */
export function setNearbyForTests(on: boolean | null): void {
  forced = on;
}
