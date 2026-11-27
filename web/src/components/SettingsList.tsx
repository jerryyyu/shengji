import { Fragment, useState, useSyncExternalStore } from "react";
import { useAuth } from "../auth";
import { setCompanionMode, shownAtTable, useCompanionMode } from "../companion/mode";
import { useCollection } from "../companion/feature";
import { useCoach } from "../firstTurns";
import { useMuted } from "../useMuted";
import { hapticsEnabled, isNative, setHapticsEnabled, subscribeHaptics } from "../native";
import { openHowto } from "../howto/route";
import { tapHandlers } from "../tap";
import { languageChoice, setLanguageChoice, useT } from "../i18n";
import type { LanguageChoice } from "../i18n";
import { showToast } from "../toast";
import { telemetry } from "../telemetry";

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

/** The player's settings, one list in one order wherever it is chosen:
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
  "zh-Hant": "language.zhHant",
} as const;

/** The Language row: its value is the choice, and a tap opens the choices
 *  inline under it, the way Edit name opens its field. Follow system,
 *  the default, reads the device's or the browser's languages. */
function LanguageRow() {
  const t = useT();
  const [open, setOpen] = useState(false);
  const chosen = languageChoice();
  const options: LanguageChoice[] = ["system", "en", "zh-Hans", "zh-Hant"];
  return (
    <li>
      <button type="button" className="grp-row me-language" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="grp-label">{t("language.row")}</span>
        <span className="grp-value chev me-language-value">{t(LANGUAGE_LABEL[chosen])}</span>
      </button>
      {open ? (
        <div className="grp-inset">
          <ul className="grp me-language-options" role="radiogroup" aria-label={t("language.row")}>
            {options.map((o) => (
              <li key={o}>
                <button type="button" className="grp-row me-language-option" role="radio" aria-checked={o === chosen}
                        lang={o === "system" ? undefined : o}
                        onClick={() => { setLanguageChoice(o); setOpen(false); }}>
                  <span className="grp-label">{t(LANGUAGE_LABEL[o])}</span>
                  <span className="grp-value me-language-check" aria-hidden="true">{o === chosen ? "✓" : ""}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </li>
  );
}

/** Show companions at the table, for a viewer the Collection is shown to: on
 *  the account (`/api/me` `companions`), or for a guest on this device. Off
 *  is off; any other stored mode (an older Team or Individual) reads as on. */
function CompanionsRow() {
  const t = useT();
  const account = useAuth();
  const user = account.status === "in" ? account.user : null;
  const on = shownAtTable(useCompanionMode(user));
  return (
    <li>
      <button type="button" className="grp-row me-companions" role="switch" aria-checked={on}
              onClick={() => {
                telemetry.tap(on ? "companions_off" : "companions_on");
                setCompanionMode(user, on ? "off" : "individual").catch((err: unknown) => {
                  showToast(err instanceof Error ? err.message : String(err));
                });
              }}>
        <span className="grp-label">{t("settings.companions")}</span>
        <span className={`ios-switch${on ? " on" : ""}`} aria-hidden="true" />
      </button>
    </li>
  );
}

/** Me's settings: an inset-grouped list under a Settings heading, where
 *  the whole 44 pt row is the control. Show companions at the table (only
 *  where the Collection is shown) and Language sit after the switches,
 *  before How to play; the table's menu has neither row. */
export function SettingsGroup() {
  const rows = useSettings();
  const t = useT();
  const companions = useCollection();
  const howto = rows.findIndex((r) => r.key === "howto");
  return (
    <>
      <h3 className="grp-head" id="me-settings-head">{t("settings.head")}</h3>
      <ul className="grp me-settings" aria-labelledby="me-settings-head">
        {rows.map((r, i) => (
          <Fragment key={r.key}>
          {i === howto ? <>{companions ? <CompanionsRow /> : null}<LanguageRow /></> : null}
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
