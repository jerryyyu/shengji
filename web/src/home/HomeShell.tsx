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
import { useGuestName } from "../guestName";
import QueueBar, { QueuePill, QueueStrip, useInlineQueue } from "../queue/QueueBar";
import AccountChip from "../components/AccountChip";
import GuestChip, { GuestNameSheet } from "../components/GuestChip";

export { WIDE };

/** The account's picture, or its initial on a plain disc; a guest's disc
 *  carries the initial of the name they play under. */
export function Avatar({ user, size = "sm", guestName = "" }: {
  user: AuthUser | null; size?: "sm" | "lg"; guestName?: string;
}) {
  const cls = `avatar avatar-${size}`;
  if (!user) {
    const initial = guestName.trim().slice(0, 1).toUpperCase();
    return <span className={`${cls} avatar-guest`} aria-hidden="true">{initial || "?"}</span>;
  }
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

/** The Me tab's icon: the account's picture, or the initial of the name
 *  played under (an account's or a guest's), drawn by CSS so the tab's text
 *  stays "Me". */
function TabAvatar({ user, guest }: { user: AuthUser | null; guest: string }) {
  if (user?.picture) return <img className="avatar" src={user.picture} alt="" referrerPolicy="no-referrer" />;
  const shown = user ? effectiveName(user) || user.email : guest.trim();
  return <span className="avatar tabbar-initial" aria-hidden="true" data-initial={shown.slice(0, 1).toUpperCase()} />;
}

/** A phone's tab bar: a floating glass pill over the page, above the home
 *  indicator, with a lighter capsule under the active tab that slides to the
 *  tab tapped. Me shows the player's picture or initial once there is one. */
export function TabBar({ active }: { active: Tab }) {
  const account = useAuth();
  const { name: guest } = useGuestName();
  const user = account.status === "in" ? account.user : null;
  const known = user !== null || (account.status !== "loading" && guest.trim() !== "");
  const index = TABS.findIndex((t) => t.tab === active);
  return (
    <nav className="tabbar" aria-label="Main" style={{ "--tab-index": index } as CSSProperties}>
      <span className="tabbar-capsule" aria-hidden="true" />
      {TABS.map(({ tab, label, icon: Icon }) => (
        <button key={tab} type="button" className={`tabbar-item${tab === active ? " on" : ""}`}
                aria-current={tab === active ? "page" : undefined} onClick={() => goTab(tab, active)}>
          {tab === "me" && known ? <TabAvatar user={user} guest={guest} /> : <Icon />}
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}

/** The wide layout's top bar: the wordmark (except on Play, whose page
 *  carries the title), the phone's three tabs centred, and the account chip
 *  (a guest's chip and Sign in) at the end, after the search's pill on a tab
 *  other than Play. */
export function TopBar({ active }: { active: Tab }) {
  const account = useAuth();
  const inlineQueue = useInlineQueue();
  const user = account.status === "in" ? account.user : null;
  let end: ReactNode = null;
  if (user) {
    end = <AccountChip user={user} />;
  } else if (account.status !== "loading") {
    end = (
      <>
        <GuestChip compact />
        {account.status === "out" ? (
          <button type="button" className="btn topbar-signin" onClick={() => openTab("me", "stats")}>Sign in</button>
        ) : null}
      </>
    );
  }
  return (
    <header className="topbar">
      {/* Play shows the title itself */}
      {active === "play" ? null : (
        <button type="button" className="topbar-mark" aria-label="Sheng Ji: Play" onClick={() => openTab("play")}>
          <b>升级</b><span>Sheng Ji</span>
        </button>
      )}
      <nav className="topbar-tabs" aria-label="Main">
        {TABS.map((t) => (
          <button key={t.tab} type="button" className={`topbar-tab${t.tab === active ? " on" : ""}`}
                  aria-current={t.tab === active ? "page" : undefined} onClick={() => goTab(t.tab, active)}>
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

/** Fades the new page in when the tab (or Me's section) changes by a tap. A swipe has already slid the page in, so it does not
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
  const account = useAuth();
  const guest = account.status !== "in" && account.status !== "loading";
  // Play holds the table panel itself; the other tabs keep a way back to it
  const away = active !== "play";
  const body = useRef<HTMLDivElement | null>(null);
  useTabSwipe(body, active, !wide);
  useTabFade(body, `${active}/${section ?? ""}`);
  return (
    <div className={`home ${wide ? "home-wide" : "home-narrow"}`}>
      {wide ? <TopBar active={active} /> : null}
      {wide && !inlineQueue && away ? <QueueStrip /> : null}
      <div className="home-body" ref={body}>{children}</div>
      {!wide && away ? <QueueBar /> : null}
      {wide ? null : <TabBar active={active} />}
      {/* one name editor for a guest's chip and Me's Edit name: the Play tab
          holds its own, every other tab this one */}
      {guest && away ? <GuestNameSheet /> : null}
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
