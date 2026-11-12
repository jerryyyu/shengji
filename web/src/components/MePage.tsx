import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, Ref } from "react";
import type { ReactNode } from "react";
import { auth, deleteAccount, effectiveName, useAuth } from "../auth";
import type { AuthUser } from "../auth";
import { deltaText, fetchStats, setVisibility, signed } from "../ratings/api";
import type { Loaded, MyStats as Stats } from "../ratings/api";
import { openHowto } from "../howto/route";
import { followInfoLink } from "../support/route";
import { Avatar, Segmented } from "../home/HomeShell";
import { EDIT_NAME_EVENT, WIDE, openTab, takeNameEditRequest } from "../home/route";
import { useMediaQuery } from "../phoneLayout";
import { cached, remember, tabMemory, useCachedResource, useTabScroll, viewerScope } from "../home/session";
import LargeTitlePage from "../home/LargeTitlePage";
import type { MeSection } from "../home/route";
import GoogleSignIn from "./GoogleSignIn";
import NameEditForm from "./NameEditForm";
import { SavedGames } from "./GamesList";

const SECTIONS = [
  { value: "stats", label: "Stats" },
  { value: "games", label: "Games" },
] as const;

function pct(value: number | null): string {
  return value === null ? "—" : `${Math.round(value)}%`;
}

function deltaClass(delta: number): string {
  return delta > 0 ? "delta-up" : delta < 0 ? "delta-dn" : "delta-flat";
}

/** One 44 pt row of an inset-grouped list: a label and, at the end, a value
 *  or a chevron. A row with an action is a button. */
function Row({ label, value, chevron, onClick, className = "", children, buttonRef }: {
  label: ReactNode; value?: ReactNode; chevron?: boolean; onClick?: () => void; className?: string;
  children?: ReactNode; buttonRef?: Ref<HTMLButtonElement>;
}) {
  const end = value !== undefined || chevron
    ? <span className={`grp-value${chevron ? " chev" : ""}`}>{value}</span> : null;
  if (onClick) {
    return (
      <li>
        <button ref={buttonRef} type="button" className={`grp-row ${className}`} onClick={onClick}>
          <span className="grp-label">{label}</span>{end}
        </button>
        {children}
      </li>
    );
  }
  return <li><div className={`grp-row ${className}`}><span className="grp-label">{label}</span>{end}</div>{children}</li>;
}

/** Name, rating, all-time rank and this week's change. */
function Identity({ user, stats }: { user: AuthUser; stats: Stats | null }) {
  let sub: ReactNode = " ";
  if (stats) {
    sub = (
      <>
        {stats.rating}
        {stats.rank !== null ? ` · #${stats.rank} all time` : " · unranked"}
        {" · "}
        <b className={deltaClass(stats.week_delta)}>{deltaText(stats.week_delta)}</b> this week
      </>
    );
  }
  return (
    <div className="me-who">
      <Avatar user={user} size="lg" />
      <div className="me-who-text">
        <div className="me-name">{effectiveName(user) || user.email}</div>
        <div className="me-sub">{sub}</div>
      </div>
    </div>
  );
}

function StatsBody({ stats }: { stats: Stats }) {
  const rounds = stats.rounds;
  return (
    <>
      <div className="me-tiles">
        <div className="me-tile"><b>{pct(stats.won_pct)}</b><span>rounds won</span></div>
        <div className="me-tile">
          <b>{stats.levels_per_round === null ? "—" : signed(stats.levels_per_round)}</b><span>levels / round</span>
        </div>
        <div className="me-tile"><b>{stats.best_streak}</b><span>best streak</span></div>
      </div>
      {rounds === 0 ? (
        <p className="grp-foot">No rated rounds yet. Every round you finish while signed in moves your rating.</p>
      ) : null}
      <ul className="grp me-counts">
        <Row label="Games won" value={stats.games_won} />
        <Row label="Rounds played" value={rounds} />
        <Row label="Won as defenders" value={pct(stats.defender_won_pct)} />
        <Row label="Won as attackers" value={pct(stats.attacker_won_pct)} />
      </ul>
      {stats.provisional && rounds > 0 ? (
        <p className="grp-foot">Your rating is provisional until 20 rated rounds.</p>
      ) : null}
    </>
  );
}

/** Delete account: the first tap opens an in-page confirmation, and only
 *  its own Delete button calls the server. The confirmation is a dialog:
 *  opening it focuses Cancel, Tab stays inside it, and Cancel or Escape
 *  closes it with focus back on the Delete account row. */
function DeleteAccount() {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const row = useRef<HTMLButtonElement | null>(null);
  const cancelBtn = useRef<HTMLButtonElement | null>(null);
  const dialog = useRef<HTMLDivElement | null>(null);
  const returning = useRef(false);
  useEffect(() => {
    if (confirming) cancelBtn.current?.focus();
    else if (returning.current) {
      returning.current = false;
      row.current?.focus();
    }
  }, [confirming]);
  const confirm = () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    deleteAccount()
      .then(() => {
        auth.deleted();
        openTab("play");
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };
  const cancel = () => {
    if (busy) return;
    returning.current = true;
    setConfirming(false);
    setError(null);
  };
  const onKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      cancel();
      return;
    }
    if (e.key !== "Tab") return;
    const stops = Array.from(dialog.current?.querySelectorAll<HTMLElement>("button") ?? []);
    if (stops.length === 0) return;
    const at = stops.indexOf(document.activeElement as HTMLElement);
    const next = e.shiftKey ? (at <= 0 ? stops.length - 1 : at - 1) : (at + 1) % stops.length;
    e.preventDefault();
    stops[next].focus();
  };
  if (!confirming) {
    return (
      <ul className="grp">
        <Row label="Delete account" chevron className="destructive me-delete" buttonRef={row}
             onClick={() => setConfirming(true)} />
      </ul>
    );
  }
  // busy buttons are aria-disabled rather than disabled, so focus stays put
  return (
    <div className="grp me-delete-confirm" role="alertdialog" aria-modal="true" ref={dialog} onKeyDown={onKey}
         aria-labelledby="me-delete-title" aria-describedby="me-delete-desc">
      <h3 id="me-delete-title">Delete your account?</h3>
      <p id="me-delete-desc">Your rating, your place on the leaderboard and your saved games are removed for good. This can’t be undone.</p>
      <button type="button" className="btn big danger me-delete-yes" aria-disabled={busy || undefined} onClick={confirm}>
        {busy ? "Deleting…" : "Delete account"}
      </button>
      <button ref={cancelBtn} type="button" className="btn big subtle me-delete-no" aria-disabled={busy || undefined}
              onClick={cancel}>
        Cancel
      </button>
      {error ? <div className="lobby-error" role="alert">{error}</div> : null}
    </div>
  );
}

function InfoRows() {
  return (
    <ul className="grp">
      <Row label="How to play" chevron onClick={() => openHowto()} />
      <li><a className="grp-row" href="/privacy" onClick={(e) => followInfoLink(e, "privacy")}>
        <span className="grp-label">Privacy policy</span><span className="grp-value chev" />
      </a></li>
      <li><a className="grp-row" href="/support" onClick={(e) => followInfoLink(e, "support")}>
        <span className="grp-label">Support</span><span className="grp-value chev" />
      </a></li>
    </ul>
  );
}

/** The account's rows, under both Stats and Games. The leaderboard switch
 *  moves on the tap and says it is saving; a refused save puts it back and
 *  says why next to it. */
function Settings({ user, stats, statsKey }: { user: AuthUser; stats: Stats | null; statsKey: string }) {
  const [visible, setVisible] = useState<boolean | null>(stats?.visible ?? null);
  const [saving, setSaving] = useState(false);
  // a stats refresh that lands mid-save does not undo the tap
  const savingNow = useRef(false);
  savingNow.current = saving;
  useEffect(() => { if (stats && !savingNow.current) setVisible(stats.visible); }, [stats]);
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    const open = () => { if (takeNameEditRequest()) setEditing(true); };
    open();
    window.addEventListener(EDIT_NAME_EVENT, open);
    return () => window.removeEventListener(EDIT_NAME_EVENT, open);
  }, []);
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const toggle = () => {
    if (visible === null || saving) return;
    const before = visible;
    setVisible(!before);
    setSaving(true);
    setSaveError(null);
    setVisibility(!before)
      .then((stored) => {
        setVisible(stored);
        const shown = cached<Loaded<Stats>>(statsKey);
        if (shown?.ok) remember(statsKey, { ...shown, data: { ...shown.data, visible: stored } });
      })
      .catch((e: Error) => { setVisible(before); setSaveError(e.message); })
      .finally(() => setSaving(false));
  };
  const signOut = () => {
    setSigningOut(true);
    setError(null);
    auth.signOut()
      .catch((e: Error) => setError(e.message))
      .finally(() => setSigningOut(false));
  };
  return (
    <>
      <ul className="grp">
        <li>
          <button type="button" className="grp-row me-visible" role="switch" aria-checked={visible === true}
                  disabled={visible === null} aria-disabled={saving || undefined} aria-busy={saving || undefined}
                  aria-describedby={saveError ? "me-visible-error" : undefined} onClick={toggle}>
            <span className="grp-label">Show me on the leaderboard</span>
            {saving ? <span className="grp-value me-saving">Saving…</span> : null}
            <span className={`ios-switch${visible ? " on" : ""}`} aria-hidden="true" />
          </button>
          {saveError ? <p className="grp-error" id="me-visible-error" role="alert">{saveError}</p> : null}
        </li>
        <Row label="Edit name" value={effectiveName(user)} chevron className="me-edit"
             onClick={() => setEditing((v) => !v)}>
          {editing ? <div className="grp-inset"><NameEditForm user={user} onDone={() => setEditing(false)} /></div> : null}
        </Row>
      </ul>
      <InfoRows />
      <ul className="grp">
        <Row label={signingOut ? "Signing out…" : "Sign out"} className="me-signout" onClick={signOut} />
      </ul>
      {error ? <div className="lobby-error" role="alert">{error}</div> : null}
      <DeleteAccount />
    </>
  );
}

/** A guest's Me: what an account adds, one sign-in, and the help rows. */
function GuestMe({ clientId }: { clientId: string | null }) {
  return (
    <>
      <div className="me-who">
        <Avatar user={null} size="lg" />
        <div className="me-who-text">
          <div className="me-name">Guest</div>
          <div className="me-sub">Not rated</div>
        </div>
      </div>
      {clientId ? (
        <div className="signin-card">
          <h3>Keep your games and get a rating</h3>
          <p>Sign in to save every game with replay, start at rating 1000 and appear on the leaderboard.
            Guest play stays free and needs no account.</p>
          <GoogleSignIn clientId={clientId} />
        </div>
      ) : null}
      <InfoRows />
    </>
  );
}

/** The Me tab: who you are, your stats or your saved games, and the
 *  account's settings below either. At 700px and up the two sections are
 *  the top bar's Stats and Games tabs instead: Stats keeps who you are and
 *  the settings (the leaderboard switch and Delete account live nowhere
 *  else), Games is the list alone. Leaving and coming back keeps the
 *  section, the scroll position and the last stats while fresh ones load;
 *  a different viewer or session starts from nothing. */
export default function MePage({ section, onBack }: { section: MeSection; onBack?: () => void }) {
  const wide = useMediaQuery(WIDE);
  const account = useAuth();
  const user = account.status === "in" ? account.user : null;
  useEffect(() => { tabMemory.meSection = section; }, [section]);
  // everything shown for an account is keyed by who is viewing and in which
  // session, so another account's stats are never drawn while these load
  const scope = viewerScope(account);
  const statsKey = `${scope}:stats`;
  const { value: res, reload: reloadStats } = useCachedResource<Loaded<Stats>>(user ? statsKey : null, fetchStats, user);
  // the saved-games list's own first-page reload, while Games is showing
  const reloadGames = useRef<(() => Promise<void>) | null>(null);
  const refresh = useCallback(
    () => Promise.all([reloadStats(), reloadGames.current?.()]), [reloadStats]);
  const stats = res && res.ok ? res.data : null;
  const [gamesReady, setGamesReady] = useState(false);
  useEffect(() => { if (section !== "games") setGamesReady(false); }, [section]);
  const markGamesReady = useCallback(() => setGamesReady(true), []);
  const ready = account.status === "loading" ? false
    : !user ? true
    : section === "games" ? gamesReady : res !== null;
  const scroller = useTabScroll(`me:${section}`, ready);

  let body: ReactNode;
  if (account.status === "loading") body = <p className="lb-note" role="status">Loading…</p>;
  else if (!user) body = <GuestMe clientId={account.status === "out" ? account.clientId : null} />;
  else {
    let content: ReactNode;
    if (section === "games") {
      content = <SavedGames onPlay={() => openTab("play")} cacheKey={`${scope}:games`} onReady={markGamesReady}
                             refreshRef={reloadGames} />;
    } else if (res === null) content = <p className="lb-note" role="status">Loading…</p>;
    else if (!res.ok) {
      content = <p className="lobby-error" role="alert">Could not load your stats ({res.status || "no connection"}).</p>;
    } else content = <StatsBody stats={res.data} />;
    const gamesTab = wide && section === "games";
    body = (
      <Fragment key={scope}>
        {gamesTab ? null : <Identity user={user} stats={stats} />}
        {wide ? null
          : <Segmented label="Show" options={SECTIONS} value={section} onChange={(s) => openTab("me", s)} />}
        {content}
        {gamesTab ? null : <Settings user={user} stats={stats} statsKey={statsKey} />}
      </Fragment>
    );
  }
  return (
    <LargeTitlePage className="me-page" scroller={scroller} title={wide ? (section === "games" ? "Games" : "Stats") : "Me"}
                    phone={!wide} onRefresh={refresh}
                    before={onBack ? <button className="btn subtle games-back home-back" onClick={onBack}>‹ Back to game</button> : null}>
      {body}
    </LargeTitlePage>
  );
}
