import { Fragment, createElement } from "react";
import type { ReactNode } from "react";
import { locale, useLocale } from "./locale";
import type { Locale } from "./locale";
import { MESSAGES } from "./messages";
import type { Message, Params } from "./define";

export type { Locale, LanguageChoice } from "./locale";
export { languageChoice, languageSaved, loadLanguage, locale, localeFor, reloadLanguage, setLanguageChoice, subscribeLocale, systemLocale, useLocale } from "./locale";
export type { Params } from "./define";

export type MessageKey = keyof typeof MESSAGES;

function render(msg: Message, params: Params): string {
  if (typeof msg === "function") return msg(params);
  return msg.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole);
}

/** The whole sentence for `key` in the current locale, with `{name}`
 *  placeholders filled from `params`. */
export function t(key: MessageKey, params: Params = {}): string {
  return tIn(locale(), key, params);
}

export function tIn(loc: Locale, key: MessageKey, params: Params = {}): string {
  const entry = MESSAGES[key];
  return render(loc === "zh-Hans" ? entry.zh : entry.en, params);
}

/** A sentence whose placeholders are elements (a bold delta, a link): the
 *  text around them comes from the table, the pieces from the caller. */
export function tx(key: MessageKey, parts: Record<string, ReactNode>, params: Params = {}): ReactNode {
  const entry = MESSAGES[key];
  const msg = locale() === "zh-Hans" ? entry.zh : entry.en;
  const text = render(msg, params);
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(/\{(\w+)\}/g)) {
    if (!(m[1] in parts)) continue;
    out.push(text.slice(last, m.index));
    out.push(createElement(Fragment, { key: `${m[1]}${m.index}` }, parts[m[1]]));
    last = m.index! + m[0].length;
  }
  out.push(text.slice(last));
  return createElement(Fragment, null, ...out);
}

/** `t`, subscribed to the locale: a component calls this once at the top. */
export function useT(): typeof t {
  useLocale();
  return t;
}

/** The servers name bot seats "Bot 1".."Bot 3"; a name of that form reads in
 *  the current language ("机器人 2"). `isBot`, where the caller has the
 *  seat's flag, keeps a person who typed such a name as typed; any other
 *  name is shown as it is. */
const BOT_NAME = /^Bot (\d+)$/;

export function displayName(name: string, isBot?: boolean): string {
  const bot = isBot === false ? null : BOT_NAME.exec(name);
  return bot ? t("common.botN", { n: bot[1] }) : name;
}

export function isZh(): boolean {
  return locale() === "zh-Hans";
}
