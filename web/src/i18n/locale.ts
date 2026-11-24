import { useSyncExternalStore } from "react";
import { isNative } from "../native";

/** The languages the app speaks. zh-Hans is Simplified Chinese; Traditional
 *  Chinese (zh-Hant, zh-TW, zh-HK, zh-MO) reads English until it has its own
 *  table. */
export type Locale = "en" | "zh-Hans";

/** The Language row's choice: a fixed language, or the device's. */
export type LanguageChoice = "system" | Locale;

const LANGUAGE_KEY = "shengji.language";

/** Capacitor's Preferences plugin (UserDefaults), reached by name through the
 *  bridge the shell injects, as keychain.ts reaches the Keychain. */
export const PREFERENCES_PLUGIN = "Preferences";

type Method = (opts?: Record<string, unknown>) => Promise<unknown>;

interface Bridge {
  isPluginAvailable?: (name: string) => boolean;
  registerPlugin?: (name: string) => Record<string, Method | undefined>;
  Plugins?: Record<string, Record<string, Method | undefined> | undefined>;
}

/** The app's native store for the choice. The hosted page and the bundled
 *  offline page are two origins with two localStorages; UserDefaults is one
 *  per app, so an explicit choice made on either holds on both. Null in a
 *  browser and in a shell built without the plugin. */
function nativeStore(name: "get" | "set" | "remove"): Method | null {
  if (!followsSystem()) return null;
  const cap = (window as unknown as { Capacitor?: Bridge }).Capacitor;
  if (!cap) return null;
  try {
    if (typeof cap.isPluginAvailable === "function" && !cap.isPluginAvailable(PREFERENCES_PLUGIN)) return null;
    const proxy = cap.registerPlugin?.(PREFERENCES_PLUGIN) ?? cap.Plugins?.[PREFERENCES_PLUGIN];
    const fn = proxy?.[name];
    return typeof fn === "function" ? fn : null;
  } catch {
    return null;
  }
}

function parseChoice(v: unknown): LanguageChoice {
  return v === "en" || v === "zh-Hans" ? v : "system";
}

function storeLocal(c: LanguageChoice): void {
  try {
    if (c === "system") localStorage.removeItem(LANGUAGE_KEY);
    else localStorage.setItem(LANGUAGE_KEY, c);
  } catch {
    /* storage blocked; the choice holds for this session */
  }
}

/** The locale a list of BCP 47 tags asks for: zh-Hans for any Simplified
 *  Chinese tag, English for everything else, Traditional Chinese included. */
export function localeFor(tags: readonly string[]): Locale {
  for (const raw of tags) {
    const tag = raw.toLowerCase();
    if (tag === "zh" || tag.startsWith("zh-")) {
      const traditional = /^zh-(hant|tw|hk|mo)\b/.test(tag) || tag.includes("-hant");
      return traditional ? "en" : "zh-Hans";
    }
    if (tag) return "en";
  }
  return "en";
}

export function systemLocale(): Locale {
  if (typeof navigator === "undefined") return "en";
  const tags = navigator.languages?.length ? navigator.languages : [navigator.language ?? ""];
  return localeFor(tags);
}

function storedChoice(): LanguageChoice {
  try {
    return parseChoice(localStorage.getItem(LANGUAGE_KEY));
  } catch {
    return "system";
  }
}

/** Follow system is the app's default. The website stays English unless
 *  its Language row picks 中文, so a web guest sees what they saw before. */
export function followsSystem(): boolean {
  try {
    return isNative();
  } catch {
    return false;
  }
}

let choice: LanguageChoice = storedChoice();
let current: Locale = resolve(choice);
const listeners = new Set<() => void>();

function resolve(c: LanguageChoice): Locale {
  if (c !== "system") return c;
  return followsSystem() ? systemLocale() : "en";
}

function apply(): void {
  current = resolve(choice);
  if (typeof document !== "undefined") document.documentElement.lang = current === "zh-Hans" ? "zh-Hans" : "en";
  for (const cb of listeners) cb();
}

export function locale(): Locale {
  return current;
}

export function languageChoice(): LanguageChoice {
  return choice;
}

/** Sets the choice: this origin's storage, and in the app the native store
 *  too, so the other launch path reads it. Follow system clears both. */
export function setLanguageChoice(next: LanguageChoice): void {
  choice = next;
  storeLocal(next);
  apply();
  const write = nativeStore(next === "system" ? "remove" : "set");
  if (!write) return;
  saving = write(next === "system" ? { key: LANGUAGE_KEY } : { key: LANGUAGE_KEY, value: next })
    .then(() => undefined, () => undefined);
}

let saving: Promise<void> = Promise.resolve();

/** Settles once the last choice has reached the native store. */
export function languageSaved(): Promise<void> {
  return saving;
}

/** How long the first render waits for the native store before it draws
 *  with this origin's copy of the choice. */
export const NATIVE_READ_MS = 400;

/** In the app, reads the choice from the native store before the first
 *  render (main.tsx waits on it), so whichever launch path opens draws in
 *  the language chosen on either. Null when there is no native store: the
 *  browser renders at once from its own storage. */
export function loadLanguage(waitMs = NATIVE_READ_MS): Promise<void> | null {
  const read = nativeStore("get");
  if (!read) return null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<"late">((resolve) => { timer = setTimeout(() => resolve("late"), waitMs); });
  return Promise.race([read({ key: LANGUAGE_KEY }), late])
    .then((r) => {
      if (r === "late") return;
      choice = parseChoice((r as { value?: unknown } | undefined)?.value);
      storeLocal(choice);
      apply();
    }, () => undefined)
    .finally(() => clearTimeout(timer));
}

/** Re-reads storage and the device: on start, and in tests after storage is
 *  cleared. */
export function reloadLanguage(): void {
  choice = storedChoice();
  apply();
}

export function subscribeLocale(cb: () => void): () => void {
  listeners.add(cb);
  return () => { listeners.delete(cb); };
}

/** The live locale; a component that shows translated text calls this (or
 *  useT) so a change in Me redraws it, memoized components included. */
export function useLocale(): Locale {
  return useSyncExternalStore(subscribeLocale, locale, locale);
}

if (typeof window !== "undefined") {
  window.addEventListener?.("languagechange", () => { if (choice === "system") apply(); });
}

apply();
