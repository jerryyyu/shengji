import { OFFLINE } from "./offlineMode";

/**
 * The reload gate: a page whose build differs from the one the server now
 * serves reloads itself, silently, at the next moment nothing is lost by it.
 *
 * The server names its page's build in `heartbeat_ready` (the meta tag the
 * build writes into index.html, read once at startup); this page's own build
 * is the same tag in the document it was loaded from. A dev page or server
 * has no tag, and the gate stays shut.
 *
 * A moment is safe when App says the seat is (no table, room or queue), no
 * sheet or queue layer is
 * open and no text field is focused or holds a draft. The gate is tried when
 * the server names its build, when that seat state changes, and when the tab
 * comes back into view. Offline, and in the app's bundled copy, it never
 * opens: the page plays on the device. The page reloads at most once per
 * server build per tab, so a server whose page still differs after a reload
 * leaves the page where it is.
 */

const RELOADED_KEY = "shengji.reloadedFor";
const OPEN_LAYER = ".q-layer, [aria-modal='true']";
const TEXT_INPUT = "textarea, input:not([type]), input[type='text'], input[type='search'], " +
  "input[type='email'], input[type='tel'], input[type='url'], input[type='password'], input[type='number']";

let serverBuild: string | null = null;
let seatSafe = false;

/** The build of the document this page was loaded from, or null. */
export function pageBuild(): string | null {
  if (typeof document === "undefined") return null;
  return document.querySelector<HTMLMetaElement>("meta[name='shengji-build']")?.content || null;
}

/** The server's page build, as its `heartbeat_ready` names it. */
export function noteServerBuild(build: unknown): void {
  serverBuild = typeof build === "string" && build !== "" ? build : null;
  tryReload();
}

/** Whether App's state lets the page go now: no seat a reload would drop. */
export function setSeatSafe(safe: boolean): void {
  seatSafe = safe;
  tryReload();
}

function editing(): boolean {
  const active = document.activeElement;
  if (active instanceof HTMLElement && (active.isContentEditable || active.matches(TEXT_INPUT))) return true;
  for (const el of document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(TEXT_INPUT)) {
    if (el.value !== "") return true;
  }
  return false;
}

function tryReload(): void {
  if (serverBuild === null || OFFLINE || location.protocol === "capacitor:") return;
  const mine = pageBuild();
  if (mine === null || mine === serverBuild) return;
  if (!seatSafe || document.querySelector(OPEN_LAYER) || editing()) return;
  try {
    if (sessionStorage.getItem(RELOADED_KEY) === serverBuild) return;
    sessionStorage.setItem(RELOADED_KEY, serverBuild);
  } catch {
    return;   // no record of a reload means no guard against a loop
  }
  location.reload();
}

function onVisibility(): void {
  if (document.visibilityState === "visible") tryReload();
}

/** App's mount: try the gate whenever the tab comes back into view. The
 *  returned stop forgets the server's build and the seat state. */
export function startReloadGate(): () => void {
  document.addEventListener("visibilitychange", onVisibility);
  return () => {
    document.removeEventListener("visibilitychange", onVisibility);
    serverBuild = null;
    seatSafe = false;
  };
}
