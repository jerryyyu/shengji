import { Fragment, useState, useSyncExternalStore } from "react";
import { useCoach } from "../firstTurns";
import { useMuted } from "../useMuted";
import { hapticsEnabled, isNative, setHapticsEnabled, subscribeHaptics } from "../native";
import { openHowto } from "../howto/route";
import { tapHandlers } from "../tap";
import { languageChoice, setLanguageChoice, useT } from "../i18n";
import type { LanguageChoice } from "../i18n";
import { followsSystem } from "../i18n/locale";

function useHaptics(): boolean {
  return useSyncExternalStore(subscribeHaptics, hapticsEnabled);
}

interface Setting {
  key: string;
  label: string;
  /** A switch's state; undefined for a row that opens a page. */
  on?: boolean;
  act: () => void;
}

/** The player's settings, one list in one order wherever it is shown:
 *  Coach, Sound, Haptics (only inside the app: a browser has no haptics to
 *  turn off) and How to play. Every switch reads the same store as the
 *  table, so a flip in Me is the table's state and the other way round. */
function useSettings(): Setting[] {
  const [coachOn, toggleCoach] = useCoach();
  const [muted, toggleSound] = useMuted();
  const haptics = useHaptics();
  const t = useT();
  const rows: Setting[] = [
    { key: "coach", label: t("settings.coach"), on: coachOn, act: toggleCoach },
    { key: "sound", label: t("settings.sound"), on: !muted, act: toggleSound },
  ];
  if (isNative()) rows.push({ key: "haptics", label: t("settings.haptics"), on: haptics, act: () => setHapticsEnabled(!haptics) });
  rows.push({ key: "howto", label: t("settings.howto"), act: () => openHowto() });
  return rows;
}

const LANGUAGE_LABEL = {
  system: "language.system",
  en: "language.en",
  "zh-Hans": "language.zh",
} as const;

/** The Language row: its value is the choice, and a tap opens the choices
 *  inline under it, the way Edit name opens its field. The app offers
 *  Follow system; the website, which stays English unless asked, offers the
 *  two languages. */
function LanguageRow() {
  const t = useT();
  const [open, setOpen] = useState(false);
  const chosen = languageChoice();
  const options: LanguageChoice[] = followsSystem() ? ["system", "en", "zh-Hans"] : ["en", "zh-Hans"];
  const shown: LanguageChoice = chosen === "system" && !followsSystem() ? "en" : chosen;
  return (
    <li>
      <button type="button" className="grp-row me-language" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="grp-label">{t("language.row")}</span>
        <span className="grp-value chev me-language-value">{t(LANGUAGE_LABEL[shown])}</span>
      </button>
      {open ? (
        <div className="grp-inset">
          <ul className="grp me-language-options" role="radiogroup" aria-label={t("language.row")}>
            {options.map((o) => (
              <li key={o}>
                <button type="button" className="grp-row me-language-option" role="radio" aria-checked={o === shown}
                        lang={o === "zh-Hans" ? "zh-Hans" : o === "en" ? "en" : undefined}
                        onClick={() => { setLanguageChoice(o); setOpen(false); }}>
                  <span className="grp-label">{t(LANGUAGE_LABEL[o])}</span>
                  <span className="grp-value me-language-check" aria-hidden="true">{o === shown ? "✓" : ""}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </li>
  );
}

/** Me's settings: an inset-grouped list under a Settings heading, where
 *  the whole 44 pt row is the control. Language sits after the switches,
 *  before How to play; the table's menu has no Language row. */
export function SettingsGroup() {
  const rows = useSettings();
  const t = useT();
  const howto = rows.findIndex((r) => r.key === "howto");
  return (
    <>
      <h3 className="grp-head" id="me-settings-head">{t("settings.head")}</h3>
      <ul className="grp me-settings" aria-labelledby="me-settings-head">
        {rows.map((r, i) => (
          <Fragment key={r.key}>
          {i === howto ? <LanguageRow /> : null}
          <li>
            {r.on === undefined ? (
              <button type="button" className={`grp-row me-${r.key}`} onClick={r.act}>
                <span className="grp-label">{r.label}</span><span className="grp-value chev" />
              </button>
            ) : (
              <button type="button" className={`grp-row me-${r.key}`} role="switch" aria-checked={r.on} onClick={r.act}>
                <span className="grp-label">{r.label}</span>
                <span className={`ios-switch${r.on ? " on" : ""}`} aria-hidden="true" />
              </button>
            )}
          </li>
          </Fragment>
        ))}
      </ul>
    </>
  );
}

/** The same settings as rows of the table's `⋯` menu, each a label with
 *  its switch (or a chevron for a page). `onOpenPage` closes the menu before
 *  How to play opens over the game. */
export function SettingsMenuRows({ onOpenPage }: { onOpenPage: () => void }) {
  const rows = useSettings();
  return (
    <>
      {rows.map((r) => r.on === undefined ? (
        <button key={r.key} className={`hud-menu-row ${r.key}-row`} role="menuitem"
                {...tapHandlers(() => { onOpenPage(); r.act(); })}>
          <span>{r.label}</span><span className="hud-menu-chev" aria-hidden="true">›</span>
        </button>
      ) : (
        <button key={r.key} className={`hud-menu-row ${r.key}-row`} role="menuitemcheckbox" aria-checked={r.on}
                {...tapHandlers(r.act)}>
          <span>{r.label}</span><span className={`ios-switch${r.on ? " on" : ""}`} aria-hidden="true" />
        </button>
      ))}
    </>
  );
}
