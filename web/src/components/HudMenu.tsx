import { useEffect, useRef, useState } from "react";
import { useMenuKeys } from "../useMenuKeys";
import { usePresence } from "../usePresence";
import { OFFLINE } from "../offlineMode";
import { COPIED_MS, shareInvite } from "../codes";
import LeaveSheet from "./LeaveSheet";
import { conn } from "../ws";
import { SettingsMenuRows } from "./SettingsList";
import { clearNearbyLogFile, copyNearbyLog, nearbyLogFileOn, useNearbyDebug, useNearbyKeepalive, useNearbySoak } from "../nearbyDebug";
import { tapHandlers } from "../tap";

/** The table's one `⋯` menu, the same on a phone and a desktop; the header
 *  beside it holds only the game's state. Its rows, in order: the game's
 *  mode as a label (Ranked or Casual, not a switch), the table's
 *  own rows as the table panel draws them (the code with its Invite link,
 *  then Allow joiners for the table's opener), the player's settings (the
 *  same list as Me's: Coach, Sound, Haptics in the app, How to play), then
 *  a red Leave game, which closes the menu and opens the one leave sheet.
 *  Offline there is no code and no invite: an offline game plays to its end
 *  on this device. A nearby table is the exception: its code is in the same
 *  place, without the Invite link (the code is the only way in), and its
 *  host has Allow joiners. Labels only, no sub-lines.
 *
 *  Keyboard: Enter or Space on `⋯` opens it with focus on the first row,
 *  ArrowUp and ArrowDown move between rows (wrapping), Home and End go to
 *  the ends, and Escape closes it and returns focus to `⋯`. */
export default function HudMenu({ room, mode, ranked = false, guest = false, offline = OFFLINE, nearby = false, allowJoiners, opener = true }: {
  room: string; ranked?: boolean; offline?: boolean;
  /** A nearby table: offline, with its code and Allow joiners. */
  nearby?: boolean;
  /** The game's mode, a plain label at the top of the menu; the header carries none. */
  mode?: "Ranked" | "Casual";
  /** A guest seat: the leave sheet speaks of no ranking. */
  guest?: boolean;
  /** The table's "Allow joiners" switch; undefined at a table without one. */
  allowJoiners?: boolean;
  /** You opened this table: only the opener sees Allow joiners. */
  opener?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [asking, setAsking] = useState(false);
  const [copied, setCopied] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  // the row to focus after the next render
  const focusNext = useRef<"first" | "last" | null>(null);
  const presence = usePresence(open);

  // the rows a keyboard can act on, in order
  const { items, onKeyDown: onMenuKey } = useMenuKeys(
    menuRef, "[role='menuitem']:not([aria-disabled='true']), [role='menuitemcheckbox']");

  useEffect(() => {
    const want = focusNext.current;
    if (!open || want === null) return;
    focusNext.current = null;
    const list = items();
    const target = want === "last" ? list[list.length - 1] : list[0];
    target?.focus();
  });

  // outside tap / Escape closes. Escape hands
  // focus back to the `⋯` button; an outside tap leaves focus where it lands.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      close();
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  });

  const close = () => setOpen(false);

  const invite = () => {
    void shareInvite(room).then((didCopy) => {
      if (!didCopy) return;
      setCopied(true);
      window.setTimeout(() => setCopied(false), COPIED_MS);
    });
  };

  const askLeave = () => {
    // the alert hands focus back to whatever had it: the `⋯` button, not a row that is going
    triggerRef.current?.focus();
    setOpen(false);
    setAsking(true);
  };

  const joiners = opener && (!offline || nearby) ? allowJoiners : undefined;
  const showCode = !offline || nearby;
  // a device-test Debug build: the link log, from the menu as well as its tab
  const debug = useNearbyDebug(nearby);
  const keepalive = useNearbyKeepalive(debug);
  const soak = useNearbySoak(debug);

  return (
    <div className="hud-more" ref={rootRef}>
      <button
        ref={triggerRef}
        className="hud-more-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="More"
        title="Table, settings, leave"
        {...tapHandlers(() => {
          if (open) { close(); return; }
          focusNext.current = "first";
          setOpen(true);
        })}
        onKeyDown={(e) => {
          // ArrowDown / ArrowUp on the closed button open the menu at its first / last row
          if (open || (e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
          e.preventDefault();
          focusNext.current = e.key === "ArrowDown" ? "first" : "last";
          setOpen(true);
        }}
      >
        ⋯
      </button>
      {presence.mounted ? (
        <div className={`hud-menu${presence.className ? ` ${presence.className}` : ""}`} role="menu"
             aria-label="More" aria-hidden={!open || undefined} inert={!open || undefined}
             ref={menuRef} onKeyDown={onMenuKey}>
          {mode ? <div className={`hud-menu-mode ${mode.toLowerCase()}`} role="none">{mode}</div> : null}
          {showCode ? (
            <div className="hud-menu-code" role="none">
              <span className="hud-menu-code-text" aria-label={`Table code ${room.split("").join(" ")}`}>{room}</span>
              {offline ? null : (
                <button className="hud-menu-row hud-menu-invite" role="menuitem" {...tapHandlers(invite)}>
                  {copied ? "Link copied" : "Invite link"}
                </button>
              )}
            </div>
          ) : null}
          {joiners === undefined ? null : (
            <button className="hud-menu-row joiners-row" role="menuitemcheckbox" aria-checked={joiners}
                    {...tapHandlers(() => conn.send({ type: "table_allow_joiners", on: !joiners }))}>
              <span>Allow joiners</span><span className={`ios-switch${joiners ? " on" : ""}`} aria-hidden="true" />
            </button>
          )}
          {debug ? (
            <button className="hud-menu-row" role="menuitem" onClick={() => { void copyNearbyLog(); close(); }}>
              <span>Copy log</span>
            </button>
          ) : null}
          {import.meta.env.VITE_SHENGJI_NEARBY === "1" && debug && nearbyLogFileOn() ? (
            <button className="hud-menu-row" role="menuitem" onClick={() => { void clearNearbyLogFile(); close(); }}>
              <span>Clear log file</span>
            </button>
          ) : null}
          {debug && keepalive ? (
            <button className="hud-menu-row joiners-row" role="menuitemcheckbox" aria-checked={keepalive.on}
                    onClick={keepalive.toggle}>
              <span>AWDL keepalive</span><span className={`ios-switch${keepalive.on ? " on" : ""}`} aria-hidden="true" />
            </button>
          ) : null}
          {debug && soak ? (
            <>
              <button className="hud-menu-row joiners-row" role="menuitemcheckbox" aria-checked={soak.autoplay}
                      onClick={soak.toggleAutoplay}>
                <span>Autoplay</span><span className={`ios-switch${soak.autoplay ? " on" : ""}`} aria-hidden="true" />
              </button>
              <button className="hud-menu-row joiners-row" role="menuitemcheckbox" aria-checked={soak.chaos}
                      onClick={soak.toggleChaos}>
                <span>Chaos</span><span className={`ios-switch${soak.chaos ? " on" : ""}`} aria-hidden="true" />
              </button>
              <button className="hud-menu-row" role="menuitem" onClick={() => { void soak.copy(); close(); }}>
                <span>Copy soak summary</span>
              </button>
            </>
          ) : null}
          {showCode ? <div className="hud-menu-sep" role="separator" /> : null}
          <SettingsMenuRows onOpenPage={close} />
          <div className="hud-menu-sep" role="separator" />
          <button className="hud-menu-row leave" role="menuitem" {...tapHandlers(askLeave)}>
            <span>Leave game</span>
          </button>
        </div>
      ) : null}
      {asking ? (
        <LeaveSheet context={{ kind: "game", ranked, guest, practice: offline }}
                    onStay={() => setAsking(false)}
                    onLeave={() => { conn.send({ type: "table_leave" }); setAsking(false); }} />
      ) : null}
    </div>
  );
}
