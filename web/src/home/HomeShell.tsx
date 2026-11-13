import { useLayoutEffect, useRef } from "react";
import type { CSSProperties, ReactNode } from "react";
import { effectiveName, useAuth } from "../auth";
import type { AuthUser } from "../auth";
import { canAnimate } from "../motion";
import { useMediaQuery } from "../phoneLayout";
import { WIDE, openTab } from "./route";
import { scrollActiveTabToTop } from "./session";
import { useTabSwipe } from "./useTabSwipe";
import type { MeSection, Tab } from "./route";
import QueueBar, { QueuePill, QueueStrip, useInlineQueue } from "../queue/QueueBar";
import AccountChip from "../components/AccountChip";
import GuestChip, { GuestNameSheet } from "../components/GuestChip";

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

/** The Me tab's icon when signed in: the account's picture, or its initial
 *  drawn by CSS so the tab's text stays "Me". */
function TabAvatar({ user }: { user: AuthUser }) {
  if (user.picture) return <img className="avatar" src={user.picture} alt="" referrerPolicy="no-referrer" />;
  const shown = effectiveName(user) || user.email;
  return <span className="avatar tabbar-initial" aria-hidden="true" data-initial={shown.slice(0, 1).toUpperCase()} />;
}

/** A phone's tab bar: a floating glass pill over the page, above the home
 *  indicator, with a lighter capsule under the active tab that slides to the
 *  tab tapped. Signed in, Me shows the account's picture or initial. */
export function TabBar({ active }: { active: Tab }) {
  const account = useAuth();
  const user = account.status === "in" ? account.user : null;
  const index = TABS.findIndex((t) => t.tab === active);
  return (
    <nav className="tabbar" aria-label="Main" style={{ "--tab-index": index } as CSSProperties}>
      <span className="tabbar-capsule" aria-hidden="true" />
      {TABS.map(({ tab, label, icon: Icon }) => (
        <button key={tab} type="button" className={`tabbar-item${tab === active ? " on" : ""}`}
                aria-current={tab === active ? "page" : undefined} onClick={() => goTab(tab, active)}>
          {tab === "me" && user ? <TabAvatar user={user} /> : <Icon />}
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}

/** The wide layout's four tabs: Me's two sections are tabs of their own. */
const WIDE_TABS: { tab: Tab; section?: MeSection; label: string }[] = [
  { tab: "play", label: "Play" },
  { tab: "leaderboard", label: "Leaderboard" },
  { tab: "me", section: "stats", label: "Stats" },
  { tab: "me", section: "games", label: "Games" },
];

/** The wide layout's top bar: the wordmark (except on Play, whose page
 *  carries the title), Play, Leaderboard, Stats and Games centred, and the
 *  account chip (a guest's chip and Sign in) at the end, after the search's pill on a tab
 *  other than Play. */
export function TopBar({ active, section = "stats" }: { active: Tab; section?: MeSection }) {
  const account = useAuth();
  const inlineQueue = useInlineQueue();
  const user = account.status === "in" ? account.user : null;
  let end: ReactNode = null;
  if (user) {
    end = <AccountChip user={user} />;
  } else if (account.status !== "loading") {
    // a guest's chip opens their name editor, which the Play tab holds
    // itself; elsewhere the bar holds it
    end = (
      <>
        <GuestChip />
        {account.status === "out" ? (
          <button type="button" className="btn topbar-signin" onClick={() => openTab("me", "stats")}>Sign in</button>
        ) : null}
        {active === "play" ? null : <GuestNameSheet />}
      </>
    );
  }
  const on = (t: (typeof WIDE_TABS)[number]) => t.tab === active && (t.tab !== "me" || t.section === section);
  const go = (t: (typeof WIDE_TABS)[number]) => {
    if (on(t)) scrollActiveTabToTop();
    else openTab(t.tab, t.section);
  };
  return (
    <header className="topbar">
      {/* Play shows the title itself */}
      {active === "play" ? null : (
        <button type="button" className="topbar-mark" aria-label="Sheng Ji: Play" onClick={() => openTab("play")}>
          <b>升级</b><span>Sheng Ji</span>
        </button>
      )}
      <nav className="topbar-tabs" aria-label="Main">
        {WIDE_TABS.map((t) => (
          <button key={t.label} type="button" className={`topbar-tab${on(t) ? " on" : ""}`}
                  aria-current={on(t) ? "page" : undefined} onClick={() => go(t)}>
            {t.label}
          </button>
        ))}
      </nav>
      <div className="topbar-end">{inlineQueue && active !== "play" ? <QueuePill /> : null}{end}</div>
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
  const inlineQueue = useInlineQueue();
  // Play holds the table panel itself; the other tabs keep a way back to it
  const away = active !== "play";
  const body = useRef<HTMLDivElement | null>(null);
  useTabSwipe(body, active, !wide);
  useTabFade(body, `${active}/${section ?? ""}`);
  return (
    <div className={`home ${wide ? "home-wide" : "home-narrow"}`}>
      {wide ? <TopBar active={active} section={section} /> : null}
      {wide && !inlineQueue && away ? <QueueStrip /> : null}
      <div className="home-body" ref={body}>{children}</div>
      {!wide && away ? <QueueBar /> : null}
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
