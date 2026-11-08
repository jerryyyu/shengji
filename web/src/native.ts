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

export type ScreenKind = "lobby" | "game";
export type HapticKind = "select" | "play" | "won" | "turn" | "declare";

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

/** The kind of haptic each table event plays (UIKit feedback generators). */
export function hapticCall(kind: HapticKind): { method: string; opts?: Record<string, unknown> } {
  switch (kind) {
    case "select": return { method: "selectionChanged" };
    case "play": return { method: "impact", opts: { style: "LIGHT" } };
    case "won": return { method: "notification", opts: { type: "SUCCESS" } };
    case "turn":
    case "declare": return { method: "impact", opts: { style: "MEDIUM" } };
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
}
