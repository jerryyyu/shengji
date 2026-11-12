import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { auth, effectiveName, useAuth } from "../auth";
import { openHowto } from "../howto/route";
import { openInfoPage } from "../support/route";
import type { AuthUser } from "../auth";
import { canAnimate } from "../motion";
import { useMediaQuery } from "../phoneLayout";
import { useMenuKeys } from "../useMenuKeys";
import { WIDE, openNameEditor, openTab } from "./route";
import { scrollActiveTabToTop } from "./session";
import { useTabSwipe } from "./useTabSwipe";
import type { MeSection, Tab } from "./route";
import QueueBar, { QueueChip, QueueStrip } from "../queue/QueueBar";

export { WIDE };

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

/** The top bar's account chip and its menu: Edit name, How to play,
 *  Privacy, Support and Sign out (Stats and Games are tabs beside it).
 *
 *  Keyboard: opening moves focus to the first row (ArrowUp on the closed chip
 *  to the last), the arrows, Home and End move between rows, and Escape
 *  closes the menu and returns focus to the chip. Tabbing out closes it. */
function AccountMenu({ user }: { user: AuthUser }) {
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
      <button ref={trigger} type="button" className="topbar-account" aria-haspopup="menu"
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
          <button type="button" role="menuitem" onClick={pick(openNameEditor)}>Edit name</button>
          <hr />
          <button type="button" role="menuitem" onClick={pick(() => openHowto())}>How to play</button>
          <button type="button" role="menuitem" onClick={pick(() => openInfoPage("privacy"))}>Privacy</button>
          <button type="button" role="menuitem" onClick={pick(() => openInfoPage("support"))}>Support</button>
          <hr />
          <button type="button" role="menuitem" onClick={pick(() => { auth.signOut().catch(() => openTab("me", "stats")); })}>
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** The wide layout's four tabs: Me's two sections are tabs of their own. */
const WIDE_TABS: { tab: Tab; section?: MeSection; label: string }[] = [
  { tab: "play", label: "Play" },
  { tab: "leaderboard", label: "Leaderboard" },
  { tab: "me", section: "stats", label: "Stats" },
  { tab: "me", section: "games", label: "Games" },
];

/** The wide layout's top bar: the wordmark, Play, Leaderboard, Stats and
 *  Games, and the account's menu (or Sign in) at the end. */
export function TopBar({ active, section = "stats" }: { active: Tab; section?: MeSection }) {
  const account = useAuth();
  const user = account.status === "in" ? account.user : null;
  let end: ReactNode = null;
  if (user) {
    end = <AccountMenu user={user} />;
  } else if (account.status === "out") {
    end = (
      <button type="button" className="btn topbar-signin" onClick={() => openTab("me", "stats")}>Sign in</button>
    );
  }
  const on = (t: (typeof WIDE_TABS)[number]) => t.tab === active && (t.tab !== "me" || t.section === section);
  const go = (t: (typeof WIDE_TABS)[number]) => {
    if (on(t)) scrollActiveTabToTop();
    else openTab(t.tab, t.section);
  };
  return (
    <header className="topbar">
      <button type="button" className="topbar-mark" aria-label="Sheng Ji: Play" onClick={() => openTab("play")}>
        <b>升级</b><span>Sheng Ji</span>
      </button>
      <nav className="topbar-tabs" aria-label="Main">
        {WIDE_TABS.map((t) => (
          <button key={t.label} type="button" className={`topbar-tab${on(t) ? " on" : ""}`}
                  aria-current={on(t) ? "page" : undefined} onClick={() => go(t)}>
            {t.label}
          </button>
        ))}
      </nav>
      <div className="topbar-end"><QueueChip />{end}</div>
    </header>
  );
}

/** How long a newly opened tab's page fades in. */
export const TAB_FADE_MS = 150;

/** Fades the new page in when the tab (or the wide layout's Me section)
 *  changes by a tap. A swipe has already slid the page in, so it does not
 *  fade too, and nothing fades on first load or under Reduce Motion. */
function useTabFade(body: { current: HTMLElement | null }, key: string): void {
  const last = useRef(key);
  useLayoutEffect(() => {
    if (last.current === key) return;
    last.current = key;
    const el = body.current;
    const page = el?.firstElementChild;
    if (!el || el.dataset.tabSwipe || !canAnimate(page)) return;
    page.animate([{ opacity: 0 }, { opacity: 1 }], { duration: TAB_FADE_MS, easing: "ease-out" });
  }, [body, key]);
}

/** The home screen's frame: the active tab's page with the tabs above it
 *  (wide) or below it (a phone, where a sideways swipe on the page moves to
 *  the tab beside it). A game, a replay and How to play are drawn without it. */
export default function HomeShell({ active, section, children }: {
  active: Tab; section?: MeSection; children: ReactNode;
}) {
  const wide = useMediaQuery(WIDE);
  const body = useRef<HTMLDivElement | null>(null);
  useTabSwipe(body, active, !wide);
  useTabFade(body, `${active}/${section ?? ""}`);
  return (
    <div className={`home ${wide ? "home-wide" : "home-narrow"}`}>
      {wide ? <TopBar active={active} section={section} /> : null}
      {wide ? <QueueStrip /> : null}
      <div className="home-body" ref={body}>{children}</div>
      {wide ? null : <QueueBar />}
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
