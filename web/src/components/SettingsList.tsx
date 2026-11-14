import { useSyncExternalStore } from "react";
import { useCoach } from "../firstTurns";
import { useMuted } from "../useMuted";
import { hapticsEnabled, isNative, setHapticsEnabled, subscribeHaptics } from "../native";
import { openHowto } from "../howto/route";

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
  const rows: Setting[] = [
    { key: "coach", label: "Coach", on: coachOn, act: toggleCoach },
    { key: "sound", label: "Sound", on: !muted, act: toggleSound },
  ];
  if (isNative()) rows.push({ key: "haptics", label: "Haptics", on: haptics, act: () => setHapticsEnabled(!haptics) });
  rows.push({ key: "howto", label: "How to play", act: () => openHowto() });
  return rows;
}

/** Me's settings: an inset-grouped list under a Settings heading, where
 *  the whole 44 pt row is the control. */
export function SettingsGroup() {
  const rows = useSettings();
  return (
    <>
      <h3 className="grp-head" id="me-settings-head">Settings</h3>
      <ul className="grp me-settings" aria-labelledby="me-settings-head">
        {rows.map((r) => (
          <li key={r.key}>
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
        ))}
      </ul>
    </>
  );
}

/** The same settings as rows of the table's `…` menu. `onOpenPage` closes
 *  the menu before How to play opens over the game. */
export function SettingsMenuRows({ onOpenPage }: { onOpenPage: () => void }) {
  const rows = useSettings();
  return (
    <>
      {rows.map((r) => r.on === undefined ? (
        <button key={r.key} className={`hud-menu-row ${r.key}-row`} role="menuitem"
                onClick={() => { onOpenPage(); r.act(); }}>
          <span>{r.label}</span>
        </button>
      ) : (
        <button key={r.key} className={`hud-menu-row ${r.key}-row`} role="menuitemcheckbox" aria-checked={r.on}
                onClick={r.act}>
          <span>{r.label}</span><span className="hud-menu-k">{r.on ? "on" : "off"}</span>
        </button>
      ))}
    </>
  );
}
