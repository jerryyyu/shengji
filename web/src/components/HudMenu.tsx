import { useEffect, useRef, useState } from "react";
import { useMuted } from "../useMuted";
import { conn } from "../ws";

/** The phone's `…` overflow (#651): kitty count, sound, invite link and leave —
 * none of them a mid-trick decision, so on a small screen they share one
 * button instead of four chips. Desktop keeps its chips (this is hidden by CSS
 * there). Leave keeps the table's two-tap confirm; a menu that closes on the
 * first tap would make the confirm impossible, so an armed Leave holds the
 * menu open until it fires or times out. */
export default function HudMenu({ room, kittyCount }: { room: string; kittyCount: number }) {
  const [open, setOpen] = useState(false);
  const [muted, toggleSound] = useMuted();
  const [armed, setArmed] = useState(false);
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => () => { if (timer.current !== null) window.clearTimeout(timer.current); }, []);

  // outside tap / Escape closes; an armed Leave reverts too
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
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
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null; }
  };

  const copyInvite = () => {
    navigator.clipboard.writeText(`${window.location.origin}/?room=${room}`)
      .then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1400); })
      .catch(() => { /* clipboard blocked; leave the label as-is */ });
  };

  const leave = () => {
    if (!armed) {
      setArmed(true);
      timer.current = window.setTimeout(() => { timer.current = null; setArmed(false); }, 3000);
      return;
    }
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null; }
    setArmed(false);
    setOpen(false);
    conn.send({ type: "leave_room" });
  };

  return (
    <div className="hud-more" ref={rootRef}>
      <button
        className="hud-more-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="More"
        title="Kitty, sound, invite, leave"
        onClick={() => (open ? close() : setOpen(true))}
      >
        …
      </button>
      {open ? (
        <div className="hud-menu" role="menu">
          <div className="hud-menu-row" role="menuitem" aria-disabled="true">
            <span>Kitty</span><span className="hud-menu-k">{kittyCount} cards</span>
          </div>
          <button className="hud-menu-row" role="menuitemcheckbox" aria-checked={!muted} onClick={toggleSound}>
            <span>Sound</span><span className="hud-menu-k">{muted ? "off" : "on"}</span>
          </button>
          <button className="hud-menu-row" role="menuitem" onClick={copyInvite}>
            <span>{copied ? "Link copied" : "Copy invite link"}</span>
          </button>
          <button className={`hud-menu-row leave${armed ? " armed" : ""}`} role="menuitem" onClick={leave}>
            <span>{armed ? "Leave game?" : "Leave game…"}</span>
          </button>
        </div>
      ) : null}
    </div>
  );
}
