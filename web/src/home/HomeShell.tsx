import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { auth, effectiveName, useAuth } from "../auth";
import { openHowto } from "../howto/route";
import { openInfoPage } from "../support/route";
import type { AuthUser } from "../auth";
import { useMediaQuery } from "../phoneLayout";
import { useMenuKeys } from "../useMenuKeys";
import { openNameEditor, openTab } from "./route";
import { scrollActiveTabToTop } from "./session";
import type { Tab } from "./route";

/** At this width and up (an iPad either way round, a desktop window) the
 *  tabs sit in a top bar; below it, a phone's bottom tab bar. */
export const WIDE = "(min-width: 700px)";

/** The account's picture, or its initial on a plain disc. */
export function Avatar({ user, size = "sm" }: { user: AuthUser | null; size?: "sm" | "lg" }) {
  const cls = `avatar avatar-${size}`;
  if (!user) return <span className={`${cls} avatar-guest`} aria-hidden="true">?</span>;
  if (user.picture) {
    return <img className={cls} src={user.picture} alt="" referrerPolicy="no-referrer" />;
  }
  const shown = effectiveName(user) || user.email;
  return <span className={cls} aria-hidden="true">{shown.slice(0, 1).toUpperCase()}</span>;
}

function PlayIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3" y="4" width="12" height="16" rx="2" />
      <path className="nofill" d="M15 6h3.5A2.5 2.5 0 0 1 21 8.5V19" />
      <path className="pip" d="M9 9l2.4 3-2.4 3-2.4-3z" />
    </svg>
  );
}

function PodiumIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="9" y="3.5" width="6" height="17" rx="1.2" />
      <rect x="2.5" y="10" width="6" height="10.5" rx="1.2" />
      <rect x="15.5" y="13" width="6" height="7.5" rx="1.2" />
    </svg>
  );
}

function PersonIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="8" r="4.2" />
      <path d="M4 20.5c0-4.2 3.6-6.8 8-6.8s8 2.6 8 6.8z" />
    </svg>
  );
}

const TABS: { tab: Tab; label: string; icon: () => ReactNode }[] = [
  { tab: "play", label: "Play", icon: PlayIcon },
  { tab: "leaderboard", label: "Leaderboard", icon: PodiumIcon },
  { tab: "me", label: "Me", icon: PersonIcon },
];

/** Open a tab; the one already showing scrolls back to its top instead. */
function goTab(tab: Tab, active: Tab): void {
  if (tab === active) scrollActiveTabToTop();
  else openTab(tab);
}

/** A phone's bottom tab bar: 49 pt over the home-indicator inset. */
export function TabBar({ active }: { active: Tab }) {
  return (
    <nav className="tabbar" aria-label="Main">
      {TABS.map(({ tab, label, icon: Icon }) => (
        <button key={tab} type="button" className={`tabbar-item${tab === active ? " on" : ""}`}
                aria-current={tab === active ? "page" : undefined} onClick={() => goTab(tab, active)}>
          <Icon />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}

/** The top bar's account chip and its menu: Me, Edit name, How to play,
 *  Privacy, Support and Sign out.
 *
 *  Keyboard: opening moves focus to the first row (ArrowUp on the closed chip
 *  to the last), the arrows, Home and End move between rows, and Escape
 *  closes the menu and returns focus to the chip. Tabbing out closes it. */
function AccountMenu({ user, active }: { user: AuthUser; active: boolean }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const menu = useRef<HTMLDivElement | null>(null);
  const focusNext = useRef<"first" | "last" | null>(null);
  const { items, onKeyDown } = useMenuKeys(menu, "[role='menuitem']");
  useEffect(() => {
    const want = focusNext.current;
    if (!open || want === null) return;
    focusNext.current = null;
    const list = items();
    (want === "last" ? list[list.length - 1] : list[0])?.focus();
  });
  useEffect(() => {
    if (!open) return;
    const away = (e: Event) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      trigger.current?.focus();
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", key);
    };
  }, [open]);
  const show = (at: "first" | "last") => { focusNext.current = at; setOpen(true); };
  const pick = (go: () => void) => () => { setOpen(false); go(); };
  return (
    <div className="topbar-menu-box" ref={box}
         onBlur={(e) => { if (open && e.relatedTarget && !box.current?.contains(e.relatedTarget as Node)) setOpen(false); }}>
      <button ref={trigger} type="button" className={`topbar-account${active ? " on" : ""}`} aria-haspopup="menu"
              aria-expanded={open} onClick={() => { if (open) setOpen(false); else show("first"); }}
              onKeyDown={(e) => {
                if (open || (e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
                e.preventDefault();
                show(e.key === "ArrowDown" ? "first" : "last");
              }}>
        <Avatar user={user} />
        <span className="topbar-account-name">{effectiveName(user) || user.email}</span>
        <span className="topbar-caret" aria-hidden="true">▾</span>
      </button>
      {open ? (
        <div className="topbar-menu" role="menu" aria-label="Account" ref={menu} onKeyDown={onKeyDown}>
          <button type="button" role="menuitem" onClick={pick(() => openTab("me"))}>Me</button>
          <button type="button" role="menuitem" onClick={pick(openNameEditor)}>Edit name</button>
          <hr />
          <button type="button" role="menuitem" onClick={pick(() => openHowto())}>How to play</button>
          <button type="button" role="menuitem" onClick={pick(() => openInfoPage("privacy"))}>Privacy</button>
          <button type="button" role="menuitem" onClick={pick(() => openInfoPage("support"))}>Support</button>
          <hr />
          <button type="button" role="menuitem" onClick={pick(() => { auth.signOut().catch(() => openTab("me")); })}>
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** The wide layout's top bar: the wordmark, Play and Leaderboard, and the
 *  account (or Sign in) at the end, which opens Me. */
export function TopBar({ active }: { active: Tab }) {
  const account = useAuth();
  const user = account.status === "in" ? account.user : null;
  let end: ReactNode = null;
  if (user) {
    end = <AccountMenu user={user} active={active === "me"} />;
  } else if (account.status === "out") {
    end = (
      <button type="button" className="btn topbar-signin" onClick={() => openTab("me")}>Sign in</button>
    );
  } else if (account.status === "off") {
    end = (
      <button type="button" className={`topbar-tab${active === "me" ? " on" : ""}`}
              aria-current={active === "me" ? "page" : undefined} onClick={() => goTab("me", active)}>Me</button>
    );
  }
  return (
    <header className="topbar">
      <button type="button" className="topbar-mark" aria-label="Sheng Ji: Play" onClick={() => openTab("play")}>
        <b>升级</b><span>Sheng Ji</span>
      </button>
      <nav className="topbar-tabs" aria-label="Main">
        {TABS.filter((t) => t.tab !== "me").map(({ tab, label }) => (
          <button key={tab} type="button" className={`topbar-tab${tab === active ? " on" : ""}`}
                  aria-current={tab === active ? "page" : undefined} onClick={() => goTab(tab, active)}>
            {label}
          </button>
        ))}
      </nav>
      <div className="topbar-end">{end}</div>
    </header>
  );
}

/** The home screen's frame: the active tab's page with the tabs above it
 *  (wide) or below it (a phone). A game, a replay and How to play are drawn
 *  without it. */
export default function HomeShell({ active, children }: { active: Tab; children: ReactNode }) {
  const wide = useMediaQuery(WIDE);
  return (
    <div className={`home ${wide ? "home-wide" : "home-narrow"}`}>
      {wide ? <TopBar active={active} /> : null}
      <div className="home-body">{children}</div>
      {wide ? null : <TabBar active={active} />}
    </div>
  );
}

/** An iOS segmented control: one choice of a few, 32 pt tall. */
export function Segmented<T extends string>({ label, options, value, onChange }: {
  label: string; options: readonly { value: T; label: string }[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" className={`segmented-btn${o.value === value ? " on" : ""}`}
                aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
