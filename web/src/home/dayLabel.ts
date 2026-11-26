import { locale, t } from "../i18n";

const DATE_LOCALE = { en: undefined, "zh-Hans": "zh-CN", "zh-Hant": "zh-TW" } as const;

/** "Today", "Yesterday" or a short date, for a day's heading. */
export function dayLabel(unix: number, now = new Date()): string {
  const then = new Date(unix * 1000);
  const start = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((start(now) - start(then)) / 86400000);
  if (days === 0) return t("home.today");
  if (days === 1) return t("home.yesterday");
  return then.toLocaleDateString(DATE_LOCALE[locale()], {
    month: "short", day: "numeric", ...(then.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
}
