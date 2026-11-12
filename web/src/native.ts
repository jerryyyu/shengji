// The iOS shell's bridge, used only inside the Capacitor app.
//
// The app's WebView loads the live site, and Capacitor injects
// `window.Capacitor` into that page, so nothing here imports a Capacitor
// package: in a browser `window.Capacitor` is absent and every export is a
// no-op. The native plugins are reached by name through the injected bridge.
//
// Orientation is decided per device class, not per viewport: an iPhone keeps
// the lobby in portrait and the game in landscape (either side); an iPad, even
// in a narrow Split View, is never locked.

import { scrollActiveTabToTop } from "./home/session";

export type ScreenKind = "lobby" | "game";
export type HapticKind = "select" | "turn" | "declare" | "won" | "error" | "refresh" | "tab";

interface PluginProxy {
  [method: string]: ((opts?: Record<string, unknown>) => Promise<unknown>) | undefined;
}

interface CapacitorGlobal {
  isNativePlatform?: () => boolean;
  registerPlugin?: (name: string) => PluginProxy;
  Plugins?: Record<string, PluginProxy | undefined>;
}

function capacitor(): CapacitorGlobal | null {
  if (typeof window === "undefined") return null;
  return (window as unknown as { Capacitor?: CapacitorGlobal }).Capacitor ?? null;
}

export function isNative(): boolean {
  try {
    return capacitor()?.isNativePlatform?.() === true;
  } catch {
    return false;
  }
}

const plugins = new Map<string, PluginProxy | null>();

function plugin(name: string): PluginProxy | null {
  if (!isNative()) return null;
  if (plugins.has(name)) return plugins.get(name)!;
  const cap = capacitor()!;
  let found: PluginProxy | null = null;
  try {
    found = cap.registerPlugin?.(name) ?? cap.Plugins?.[name] ?? null;
  } catch {
    found = cap.Plugins?.[name] ?? null;
  }
  plugins.set(name, found);
  return found;
}

/** Calls a plugin method; any failure (an older shell without the plugin,
 *  a rejected call) is swallowed, because none of these are load-bearing. */
async function call(name: string, method: string, opts?: Record<string, unknown>): Promise<unknown> {
  const fn = plugin(name)?.[method];
  if (typeof fn !== "function") return undefined;
  try {
    return await fn(opts);
  } catch {
    return undefined;
  }
}

let phone: Promise<boolean> | null = null;

/** True only in the app on an iPhone. The shell reports the device idiom,
 *  because a viewport width cannot tell an iPad in Split View from a phone. */
export function isPhone(): Promise<boolean> {
  if (!isNative()) return Promise.resolve(false);
  phone ??= call("ShengjiShell", "idiom").then(
    (r) => (r as { idiom?: string } | undefined)?.idiom === "phone");
  return phone;
}

let lastLock: ScreenKind | null = null;

/** Lobby screens portrait, the table landscape (both sides), on iPhone only. */
export async function lockFor(screen: ScreenKind): Promise<void> {
  if (!(await isPhone())) return;
  if (lastLock === screen) return;
  lastLock = screen;
  if (screen === "game") {
    // The ScreenOrientation plugin's "landscape" is one side only; the shell's
    // own method allows both, so the table turns with the phone.
    await call("ShengjiShell", "lockOrientation", { orientation: "landscape" });
  } else {
    await call("ScreenOrientation", "lock", { orientation: "portrait" });
  }
}

/** The kind of haptic each event plays (UIKit feedback generators). A round
 *  is about 25 turns, so only rare or decisive moments get one: your turn
 *  arriving (light), a declare chance (medium, it is racing), your team
 *  winning the round (success) and a refused action (error). A card select
 *  is a selection tick; your own play and a won trick are silent. A pull to
 *  refresh ticks lightly as it passes the point where letting go reloads,
 *  and a swipe that lands on the next home tab ticks lightly too. */
export function hapticCall(kind: HapticKind): { method: string; opts?: Record<string, unknown> } {
  switch (kind) {
    case "select": return { method: "selectionChanged" };
    case "turn":
    case "refresh":
    case "tab": return { method: "impact", opts: { style: "LIGHT" } };
    case "declare": return { method: "impact", opts: { style: "MEDIUM" } };
    case "won": return { method: "notification", opts: { type: "SUCCESS" } };
    case "error": return { method: "notification", opts: { type: "ERROR" } };
  }
}

let selectionPrimed = false;

export function haptic(kind: HapticKind): void {
  if (!isNative()) return;
  const { method, opts } = hapticCall(kind);
  if (method === "selectionChanged" && !selectionPrimed) {
    // The selection generator exists only between selectionStart and
    // selectionEnd; keep one open for the session.
    selectionPrimed = true;
    void call("Haptics", "selectionStart").then(() => call("Haptics", method, opts));
    return;
  }
  void call("Haptics", method, opts);
}

let lastBackGesture: boolean | null = null;

/** The shell's edge swipe back and forward through the WebView's history:
 *  on everywhere but the table, where a stray swipe would cover a live game
 *  with an earlier page. A shell without the method keeps its default. */
export async function setBackGesture(enabled: boolean): Promise<void> {
  if (!isNative() || lastBackGesture === enabled) return;
  lastBackGesture = enabled;
  await call("ShengjiShell", "setBackGesture", { enabled });
}

let lastGameMode: boolean | null = null;

/** At the table: the screen stays awake, the bottom edge defers the home
 *  gesture (a card drag near it needs a second swipe to leave) and the home
 *  indicator hides; away from it all three are the system's again. Any
 *  device, since an iPad has the same edge and indicator. */
export async function setGameMode(on: boolean): Promise<void> {
  if (!isNative() || lastGameMode === on) return;
  lastGameMode = on;
  await Promise.all([
    call("ShengjiShell", "setGameMode", { on }),
    call("SystemBars", on ? "hide" : "show", { bar: "NavigationBar" }),
  ]);
}

/** Set on <body> while the keyboard is up, so the tab bar steps aside. */
export const KEYBOARD_OPEN_CLASS = "keyboard-open";
/** The shell dispatches this on window when the status bar is tapped. */
export const STATUS_TAP_EVENT = "statusTap";

const onKeyboardShow = () => document.body.classList.add(KEYBOARD_OPEN_CLASS);
const onKeyboardHide = () => document.body.classList.remove(KEYBOARD_OPEN_CLASS);
/** The WebView shrinks only after the keyboard has risen, too late for
 *  WebKit's own scroll to the focused field, so the field is brought into
 *  view again once the page has its new height. */
const revealFocused = () => {
  if (!document.body.classList.contains(KEYBOARD_OPEN_CLASS)) return;
  const el = document.activeElement;
  if (el instanceof HTMLElement && el !== document.body) el.scrollIntoView?.({ block: "center" });
};
/** A tab page with remembered scroll answers scrollActiveTabToTop; any other
 *  scrolled screen (the Play lobby, a room) is scrolled up here. */
const onStatusTap = () => {
  scrollActiveTabToTop();
  for (const el of document.querySelectorAll<HTMLElement>(".screen")) {
    if (el.scrollTop > 0) el.scrollTo?.({ top: 0, behavior: "smooth" });
  }
};
let shellStarted = false;

/** Startup wiring for the app: no web Previous/Next/Done bar over the
 *  keyboard, the keyboard-open class from the Keyboard plugin's window events,
 *  the focused field kept in view as the page shrinks, and a status-bar tap
 *  scrolling the active tab to the top. */
export function startShell(): void {
  if (shellStarted || !isNative()) return;
  shellStarted = true;
  void call("Keyboard", "setAccessoryBarVisible", { isVisible: false });
  window.addEventListener("keyboardWillShow", onKeyboardShow);
  window.addEventListener("keyboardWillHide", onKeyboardHide);
  window.addEventListener("resize", revealFocused);
  window.addEventListener(STATUS_TAP_EVENT, onStatusTap);
}

let splashHidden = false;

/** Fades the launch splash out once the first screen has painted. */
export function hideSplash(): void {
  if (splashHidden || !isNative()) return;
  splashHidden = true;
  void call("SplashScreen", "hide", { fadeOutDuration: 200 });
}

/** Test hook: forget cached plugin lookups and state. */
export function resetNativeForTests(): void {
  plugins.clear();
  phone = null;
  lastLock = null;
  selectionPrimed = false;
  splashHidden = false;
  lastBackGesture = null;
  lastGameMode = null;
  if (shellStarted) {
    window.removeEventListener("keyboardWillShow", onKeyboardShow);
    window.removeEventListener("keyboardWillHide", onKeyboardHide);
    window.removeEventListener("resize", revealFocused);
    window.removeEventListener(STATUS_TAP_EVENT, onStatusTap);
    shellStarted = false;
  }
  document.body.classList.remove(KEYBOARD_OPEN_CLASS);
}
