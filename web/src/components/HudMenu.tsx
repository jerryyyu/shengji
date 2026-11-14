import { useEffect, useRef, useState } from "react";
import { useMenuKeys } from "../useMenuKeys";
import { usePresence } from "../usePresence";
import { OFFLINE } from "../offlineMode";
import { codeLink } from "../codes";
import LeaveAlert from "./LeaveAlert";
import { offlineGame } from "./offlineGame";
import { useOnline } from "../useOnline";
import { conn } from "../ws";
import { SettingsMenuRows } from "./SettingsList";

/** The phone's `…` overflow: the player's settings (the same list as Me's:
 * Coach, Sound, Haptics in the app, How to play), then the table's actions
 * (invite link, Allow joiners, leave) — none of them a mid-trick decision, so
 * on a small screen they share one button instead of a row of chips. The
 * kitty's count is information, not a setting: the HUD shows it during the
 * bury. Desktop keeps its chips (this
 * is hidden by CSS there). Account rows (name, saved games, sign out) live on the Me tab, so
 * this stays a table menu for signed-in players and guests alike. Leave
 * closes the menu and opens the leave alert, which waits for Keep playing or
 * Leave. Offline there is no invite link; Play online appears instead while
 * the device has a connection.
 *
 * Keyboard: opening moves focus to the first actionable row, ArrowUp and
 * ArrowDown move between rows (wrapping), Home and End go to the ends, and
 * Escape closes the menu and returns focus to the `…` button. */
export default function HudMenu({ room, ranked = false, offline = OFFLINE, allowJoiners }: {
  room: string; ranked?: boolean; offline?: boolean;
  /** A ranked table's "Allow joiners" switch; undefined elsewhere. */
  allowJoiners?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [asking, setAsking] = useState(false);
  const online = useOnline();
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
  // focus back to the `…` button; an outside tap leaves focus where it lands.
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

  const copyInvite = () => {
    navigator.clipboard.writeText(codeLink(room))
      .then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1400); })
      .catch(() => { /* clipboard blocked; leave the label as-is */ });
  };

  const askLeave = () => {
    // the alert hands focus back to whatever had it: the `…` button, not a row that is going
    triggerRef.current?.focus();
    setOpen(false);
    setAsking(true);
  };

  return (
    <div className="hud-more" ref={rootRef}>
      <button
        ref={triggerRef}
        className="hud-more-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="More"
        title="Settings, invite, leave"
        onClick={() => {
          if (open) { close(); return; }
          focusNext.current = "first";
          setOpen(true);
        }}
        onKeyDown={(e) => {
          // ArrowDown / ArrowUp on the closed button open the menu at its first / last row
          if (open || (e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
          e.preventDefault();
          focusNext.current = e.key === "ArrowDown" ? "first" : "last";
          setOpen(true);
        }}
      >
        …
      </button>
      {presence.mounted ? (
        <div className={`hud-menu${presence.className ? ` ${presence.className}` : ""}`} role="menu"
             aria-label="More" aria-hidden={!open || undefined} inert={!open || undefined}
             ref={menuRef} onKeyDown={onMenuKey}>
          <SettingsMenuRows onOpenPage={close} />
          <div className="hud-menu-sep" role="separator" />
          {offline ? null : (
            <button className="hud-menu-row" role="menuitem" onClick={copyInvite}>
              <span>{copied ? "Link copied" : "Copy invite link"}</span>
            </button>
          )}
          {allowJoiners === undefined ? null : (
            <button className="hud-menu-row" role="menuitemcheckbox" aria-checked={allowJoiners}
                    onClick={() => conn.send({ type: "allow_joiners", on: !allowJoiners })}>
              <span>Allow joiners</span><span className="hud-menu-k">{allowJoiners ? "on" : "off"}</span>
            </button>
          )}
          {offline && online ? (
            <button className="hud-menu-row" role="menuitem" onClick={() => offlineGame.goOnline()}>
              <span>Play online</span>
            </button>
          ) : null}
          <button className="hud-menu-row leave" role="menuitem" onClick={askLeave}>
            <span>Leave game</span>
          </button>
        </div>
      ) : null}
      {asking ? (
        <LeaveAlert ranked={ranked} practice={offline} onKeep={() => setAsking(false)} onLeft={() => setAsking(false)} />
      ) : null}
    </div>
  );
}
