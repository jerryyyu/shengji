import { useEffect, useRef, useState } from "react";
import { useMenuKeys } from "../useMenuKeys";
import { useMuted } from "../useMuted";
import { usePresence } from "../usePresence";
import { conn } from "../ws";
import { auth, effectiveName, useAuth } from "../auth";
import { navigate } from "../replay/route";
import NameEditForm from "./NameEditForm";
import { codeLink } from "../codes";

/** The phone's `…` overflow: kitty count, sound, invite link and leave —
 * none of them a mid-trick decision, so on a small screen they share one
 * button instead of four chips. Desktop keeps its chips (this is hidden by CSS
 * there). Leave asks first: its row turns into "Leave game? Stay / Leave"
 * and waits, with no timer, until one is chosen or the menu is closed.
 *
 * Keyboard: opening moves focus to the first actionable row, ArrowUp and
 * ArrowDown move between rows (wrapping), Home and End go to the ends, and
 * Escape closes the menu and returns focus to the `…` button. Arming Leave
 * focuses Stay, the safe choice; Stay puts focus back on the Leave row. */
export default function HudMenu({ room, kittyCount }: { room: string; kittyCount: number }) {
  const [open, setOpen] = useState(false);
  const [muted, toggleSound] = useMuted();
  const [armed, setArmed] = useState(false);
  const [copied, setCopied] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const account = useAuth();
  const [signOutError, setSignOutError] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  // the row to focus after the next render
  const focusNext = useRef<"first" | "last" | "stay" | "leave" | null>(null);
  const presence = usePresence(open);

  // the rows a keyboard can act on, in order: the kitty row is information
  // only, and an open name field keeps its own arrow keys
  const { items, onKeyDown: onMenuKey } = useMenuKeys(
    menuRef, "[role='menuitem']:not([aria-disabled='true']), [role='menuitemcheckbox'], .hud-menu-choice");

  useEffect(() => {
    const want = focusNext.current;
    if (!open || want === null) return;
    focusNext.current = null;
    const list = items();
    const target = want === "stay" ? menuRef.current?.querySelector<HTMLElement>(".hud-menu-choice")
      : want === "leave" ? menuRef.current?.querySelector<HTMLElement>(".hud-menu-row.leave")
      : want === "last" ? list[list.length - 1]
      : list[0];
    target?.focus();
  });

  // outside tap / Escape closes; an armed Leave reverts too. Escape hands
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

  const close = () => {
    setOpen(false);
    setArmed(false);
    setEditingName(false);
  };

  const copyInvite = () => {
    navigator.clipboard.writeText(codeLink(room))
      .then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1400); })
      .catch(() => { /* clipboard blocked; leave the label as-is */ });
  };

  const leave = () => {
    setArmed(false);
    setOpen(false);
    conn.send({ type: "leave_room" });
  };

  return (
    <div className="hud-more" ref={rootRef}>
      <button
        ref={triggerRef}
        className="hud-more-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="More"
        title="Kitty, sound, invite, leave"
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
          <div className="hud-menu-row" role="menuitem" aria-disabled="true">
            <span>Kitty</span><span className="hud-menu-k">{kittyCount} cards</span>
          </div>
          <button className="hud-menu-row" role="menuitemcheckbox" aria-checked={!muted} onClick={toggleSound}>
            <span>Sound</span><span className="hud-menu-k">{muted ? "off" : "on"}</span>
          </button>
          <button className="hud-menu-row" role="menuitem" onClick={copyInvite}>
            <span>{copied ? "Link copied" : "Copy invite link"}</span>
          </button>
          {account.status === "in" && account.user ? (
            <>
              {editingName ? (
                <div className="hud-menu-row hud-menu-edit" role="none">
                  <NameEditForm user={account.user} onDone={() => setEditingName(false)} />
                </div>
              ) : (
                <button className="hud-menu-row account-edit" role="menuitem"
                        onClick={() => setEditingName(true)}>
                  {account.user.picture
                    ? <img className="account-avatar" src={account.user.picture} alt="" referrerPolicy="no-referrer" />
                    : null}
                  <span className="hud-menu-account-name">
                    {effectiveName(account.user) || account.user.email}
                  </span>
                  <span className="hud-menu-k">Edit name</span>
                </button>
              )}
              <button className="hud-menu-row account-games" role="menuitem"
                      onClick={() => { close(); navigate({ page: "list" }); }}>
                <span>My games</span>
              </button>
              <button className="hud-menu-row account" role="menuitem"
                      onClick={() => {
                        // the menu stays open until the server confirms, so a
                        // failed sign-out is visible and one tap retries it
                        auth.signOut().then(close).catch(() => setSignOutError(true));
                      }}>
                <span>{signOutError ? "Sign out failed, retry" : "Sign out"}</span>
              </button>
            </>
          ) : null}
          {armed ? (
            <div className="hud-menu-row leave armed" role="group" aria-label="Leave game?">
              <span>Leave game?</span>
              <span className="hud-menu-confirm">
                <button className="hud-menu-choice" onClick={() => { focusNext.current = "leave"; setArmed(false); }}>Stay</button>
                <button className="hud-menu-choice danger" onClick={leave}>Leave</button>
              </span>
            </div>
          ) : (
            <button className="hud-menu-row leave" role="menuitem"
                    onClick={() => { focusNext.current = "stay"; setArmed(true); }}>
              <span>Leave game…</span>
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}
