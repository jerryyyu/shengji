import { useEffect, useLayoutEffect, useRef } from "react";
import type { CSSProperties, ReactNode } from "react";
import { effectiveName, useAuth } from "../auth";
import type { AuthUser } from "../auth";
import { canAnimate } from "../motion";
import { useMediaQuery } from "../phoneLayout";
import { WIDE, openTab } from "./route";
import { scrollActiveTabToTop } from "./session";
import { tabOrder, useTabSwipe } from "./useTabSwipe";
import { clearErrorToast } from "../toast";
import type { MeSection, Tab } from "./route";
import { useGuestName } from "../guestName";
import YourTablePill from "../queue/YourTablePill";
import { SeatedAtContext } from "../queue/seatedAt";
import type { SeatedAt } from "../queue/seatedAt";
import AccountChip from "../components/AccountChip";
import { useT } from "../i18n";
import type { MessageKey } from "../i18n";
import GuestChip from "../components/GuestChip";
import { Portrait } from "../companion/Companion";
import { lookAccount, useNewLook } from "../companion/seen";
import { useCollection } from "../companion/feature";
import { refreshAccount } from "../companion/writes";

export { WIDE };

/** A person's picture: where the Collection is shown, the portrait of their
 *  equipped companion (a guest's is the default); elsewhere the account's
 *  picture, or its initial on a plain disc, and a guest's disc carries the
 *  initial of the name they play under. */
export function Avatar({ user, size = "sm", guestName = "" }: {
  user: AuthUser | null; size?: "sm" | "lg"; guestName?: string;
}) {
  const companions = useCollection();
  const cls = `avatar avatar-${size}`;
  if (companions) {
    return <span className={`${cls} avatar-portrait`}><Portrait look={user?.look} size={size === "lg" ? 64 : 28} /></span>;
  }
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

/** Collection: four small tiles; the selected tab fills one of them. */
function TilesIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="tiles-icon">
      <rect className="tile-on" x="3.5" y="3.5" width="7.5" height="7.5" rx="2" />
      <rect className="nofill" x="13" y="3.5" width="7.5" height="7.5" rx="2" />
      <rect className="nofill" x="3.5" y="13" width="7.5" height="7.5" rx="2" />
      <rect className="nofill" x="13" y="13" width="7.5" height="7.5" rx="2" />
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

const TABS: { tab: Tab; name: MessageKey; icon: () => ReactNode }[] = [
  { tab: "play", name: "home.tabPlay", icon: PlayIcon },
  { tab: "leaderboard", name: "home.tabLeaderboard", icon: PodiumIcon },
  { tab: "collection", name: "home.tabCollection", icon: TilesIcon },
  { tab: "me", name: "home.tabMe", icon: PersonIcon },
];

/** Open a tab; the one already showing scrolls back to its top instead. */
function goTab(tab: Tab, active: Tab): void {
  if (tab === active) scrollActiveTabToTop();
  else openTab(tab);
}

/** The Me tab's icon: the player's portrait where the Collection is shown;
 *  elsewhere the account's picture, or the initial of the name played under
 *  (an account's or a guest's), drawn by CSS so the tab's text stays "Me". */
function TabAvatar({ user, guest, companions }: { user: AuthUser | null; guest: string; companions: boolean }) {
  if (companions) return <span className="avatar avatar-portrait"><Portrait look={user?.look} size={26} /></span>;
  if (user?.picture) return <img className="avatar" src={user.picture} alt="" referrerPolicy="no-referrer" />;
  const shown = user ? effectiveName(user) || user.email : guest.trim();
  return <span className="avatar tabbar-initial" aria-hidden="true" data-initial={shown.slice(0, 1).toUpperCase()} />;
}

/** The tabs this viewer has, in order. */
function useTabs() {
  const companions = useCollection();
  const order = tabOrder(companions);
  return { companions, order, tabs: TABS.filter((x) => order.includes(x.tab)) };
}

/** The gold dot a tab carries while it holds something new. */
function NewDot() {
  return <span className="tab-dot" aria-hidden="true" />;
}

/** A phone's tab bar: a floating glass pill over the page, above the home
 *  indicator, with a lighter capsule under the active tab that slides to the
 *  tab tapped. Me shows the player's portrait once there is a player. */
export function TabBar({ active }: { active: Tab }) {
  const t = useT();
  const account = useAuth();
  const { name: guest } = useGuestName();
  const user = account.status === "in" ? account.user : null;
  const known = user !== null || (account.status !== "loading" && guest.trim() !== "");
  const { companions, tabs } = useTabs();
  const fresh = useNewLook(companions ? lookAccount(user) : null, user?.looks) && active !== "collection";
  const index = tabs.findIndex((x) => x.tab === active);
  return (
    <nav className="tabbar" aria-label={t("home.navMain")}
         style={{ "--tab-index": index, "--tab-count": tabs.length } as CSSProperties}>
      <span className="tabbar-capsule" aria-hidden="true" />
      {tabs.map(({ tab, name, icon: Icon }) => (
        <button key={tab} type="button" className={`tabbar-item${tab === active ? " on" : ""}`}
                aria-current={tab === active ? "page" : undefined} onClick={() => goTab(tab, active)}>
          {tab === "me" && known ? <TabAvatar user={user} guest={guest} companions={companions} /> : <Icon />}
          {tab === "collection" && fresh ? <NewDot /> : null}
          <span>{t(name)}</span>
        </button>
      ))}
    </nav>
  );
}

/** The wide layout's top bar: no strip of its own, only the phone's
 *  tabs as a glass pill centred over the page and the account chip
 *  at the end (a guest's opens the identity sheet), after the Your table
 *  pill on a tab other than Play. */
export function TopBar({ active }: { active: Tab }) {
  const t = useT();
  const account = useAuth();
  const user = account.status === "in" ? account.user : null;
  const { companions, tabs } = useTabs();
  const fresh = useNewLook(companions ? lookAccount(user) : null, user?.looks) && active !== "collection";
  let end: ReactNode = null;
  if (user) {
    end = <AccountChip user={user} compact />;
  } else if (account.status !== "loading") {
    end = <GuestChip compact />;
  }
  return (
    <header className="topbar">
      <nav className="topbar-tabs" aria-label={t("home.navMain")}>
        {tabs.map((x) => (
          <button key={x.tab} type="button" className={`topbar-tab${x.tab === active ? " on" : ""}`}
                  aria-current={x.tab === active ? "page" : undefined} onClick={() => goTab(x.tab, active)}>
            {t(x.name)}
            {x.tab === "collection" && fresh ? <NewDot /> : null}
          </button>
        ))}
      </nav>
      <div className="topbar-end">{active !== "play" ? <YourTablePill /> : null}{end}</div>
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

/** An error toast is about the tab it came from: a tab change takes it down. */
function useTabClearsError(active: Tab): void {
  const last = useRef(active);
  useEffect(() => {
    if (last.current === active) return;
    last.current = active;
    clearErrorToast();
  }, [active]);
}

/** The home screen's frame: the active tab's page with the tabs above it
 *  (wide) or below it (a phone, where a sideways swipe on the page moves to
 *  the tab beside it). A game, a replay and How to play are drawn without it.
 *  `seatedAt` names a game you sit at, for the Your table pill that
 *  the top bar (wide) or the page's title row (a phone) shows on other tabs. */
export default function HomeShell({ active, section, seatedAt = null, children }: {
  active: Tab; section?: MeSection; seatedAt?: SeatedAt; children: ReactNode;
}) {
  const wide = useMediaQuery(WIDE);
  const body = useRef<HTMLDivElement | null>(null);
  const companions = useCollection();
  useTabSwipe(body, active, !wide, tabOrder(companions));
  // back on the tabs after a game: read the counts a round may have moved
  useEffect(() => {
    if (companions) void refreshAccount();
  }, [companions]);
  useTabFade(body, `${active}/${section ?? ""}`);
  useTabClearsError(active);
  return (
    <SeatedAtContext.Provider value={seatedAt}>
      <div className={`home ${wide ? "home-wide" : "home-narrow"}`}>
        {wide ? <TopBar active={active} /> : null}
        <div className="home-body" ref={body}>{children}</div>
        {wide ? null : <TabBar active={active} />}
      </div>
    </SeatedAtContext.Provider>
  );
}

/** An iOS segmented control: one choice of a few, 44 pt tall. */
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
