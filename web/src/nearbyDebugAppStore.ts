// What nearbyUi.tsx takes from nearbyDebug.tsx, in the page the App Store
// archive bundles (VITE_SHENGJI_APP_STORE=1; vite.config.ts swaps it in):
// nothing. No log pane, no hidden switch, no log file or upload, no soak, so
// the bundle holds none of their modules; the App Store binary reports none
// of `debug`, `logFile` or `chaos` either. Types only from nearbyDebug.tsx,
// so the two keep one interface and this file imports none of its code.
import type * as Full from "./nearbyDebug";

export const clearNearbyLogFile: typeof Full.clearNearbyLogFile = () => Promise.resolve(false);
export const copyNearbyLog: typeof Full.copyNearbyLog = () => Promise.resolve(false);
export const startNearbyLogFile: typeof Full.startNearbyLogFile = () => {};
export const nearbySoakSwitchOn: typeof Full.nearbySoakSwitchOn = () => false;
export const nearbySoakSwitchTap: typeof Full.nearbySoakSwitchTap = () => {};
export const subscribeNearbySoakSwitch: typeof Full.subscribeNearbySoakSwitch = () => () => {};
export const uploadNearbyLogNow: typeof Full.uploadNearbyLogNow = () => Promise.resolve();
export const useNearbyDebug: typeof Full.useNearbyDebug = () => false;
export const useNearbyKeepalive: typeof Full.useNearbyKeepalive = () => null;
export const useNearbyLogFile: typeof Full.useNearbyLogFile = () => false;
export const useNearbySoak: typeof Full.useNearbySoak = () => null;
export const useNearbySoakSwitch: typeof Full.useNearbySoakSwitch = () => false;
const NearbyDebugPane: typeof Full.default = () => null;
export default NearbyDebugPane;
