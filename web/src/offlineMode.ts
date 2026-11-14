const OFFLINE_KEY = "shengji.offline";

/**
 * Offline mode: no game server, a local one in the page (src/offline/server)
 * with SmartBot seats. On for the app's bundled page (served from its own
 * capacitor:// origin, which the shell shows when the live site cannot load)
 * and for `?offline=1`, which this tab remembers until `?offline=0`.
 */
function detectOffline(): boolean {
  if (typeof location === "undefined") return false;
  if (location.protocol === "capacitor:") return true;
  const param = new URLSearchParams(location.search).get("offline");
  try {
    if (param === "1") sessionStorage.setItem(OFFLINE_KEY, "1");
    if (param === "0") sessionStorage.removeItem(OFFLINE_KEY);
    return sessionStorage.getItem(OFFLINE_KEY) === "1";
  } catch {
    return param === "1";
  }
}

export const OFFLINE = detectOffline();
