import { useSyncExternalStore } from "react";
import { isNative } from "../native";

/** The languages the app speaks. zh-Hans is Simplified Chinese; Traditional
 *  Chinese (zh-Hant, zh-TW, zh-HK, zh-MO) reads English until it has its own
 *  table. */
export type Locale = "en" | "zh-Hans";

/** The Language row's choice: a fixed language, or the device's. */
export type LanguageChoice = "system" | Locale;

const LANGUAGE_KEY = "shengji.language";

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
    const v = localStorage.getItem(LANGUAGE_KEY);
    return v === "en" || v === "zh-Hans" ? v : "system";
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

export function setLanguageChoice(next: LanguageChoice): void {
  choice = next;
  try {
    if (next === "system") localStorage.removeItem(LANGUAGE_KEY);
    else localStorage.setItem(LANGUAGE_KEY, next);
  } catch {
    /* storage blocked; the choice holds for this session */
  }
  apply();
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
