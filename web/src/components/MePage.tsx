import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { auth, deleteAccount, effectiveName, isUnlinkedDevice, useAuth } from "../auth";
import { useOnThisDeviceLine } from "../deviceAccount";
import type { AuthUser } from "../auth";
import { deltaText, fetchStats, setVisibility, signed } from "../ratings/api";
import type { Loaded, MyStats as Stats } from "../ratings/api";
import { followInfoLink } from "../support/route";
import { isNative } from "../native";
import { Avatar, Segmented } from "../home/HomeShell";
import { WIDE, openTab } from "../home/route";
import { useMediaQuery } from "../phoneLayout";
import { cached, remember, tabMemory, useCachedResource, useTabScroll, viewerScope } from "../home/session";
import LargeTitlePage from "../home/LargeTitlePage";
import type { MeSection } from "../home/route";
import NameEditForm from "./NameEditForm";
import ConfirmSheet from "./ConfirmSheet";
import { SavedGames } from "./GamesList";
import { useScreen } from "../telemetry";
import { SettingsGroup } from "./SettingsList";
import { GUEST_LINE, guestName, useGuestName } from "../guestName";
import { randomName } from "../randomName";

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
function Row({ label, value, chevron, onClick, className = "", children }: {
  label: ReactNode; value?: ReactNode; chevron?: boolean; onClick?: () => void; className?: string;
  children?: ReactNode;
}) {
  const end = value !== undefined || chevron
    ? <span className={`grp-value${chevron ? " chev" : ""}`}>{value}</span> : null;
  if (onClick) {
    return (
      <li>
        <button type="button" className={`grp-row ${className}`} onClick={onClick}>
          <span className="grp-label">{label}</span>{end}
        </button>
        {children}
      </li>
    );
  }
  return <li><div className={`grp-row ${className}`}><span className="grp-label">{label}</span>{end}</div>{children}</li>;
}

/** Name, rating, all-time rank and this week's change; for the app's own
 *  account with no Apple or Google sign-in, the one line that it lives on
 *  this iPhone (or iPad) only. */
function Identity({ user, stats }: { user: AuthUser; stats: Stats | null }) {
  const where = useOnThisDeviceLine();
  let sub: ReactNode = " ";
  if (isUnlinkedDevice(user)) sub = where;
  else if (stats) {
    sub = (
      <>
        {stats.rating.toLocaleString()}
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
        <p className="grp-foot">No ranked rounds yet.</p>
      ) : null}
      <ul className="grp me-counts">
        <Row label="Games won" value={stats.games_won} />
        <Row label="Rounds played" value={rounds} />
        <Row label="Won as defenders" value={pct(stats.defender_won_pct)} />
        <Row label="Won as attackers" value={pct(stats.attacker_won_pct)} />
      </ul>
      {stats.provisional && rounds > 0 ? (
        <p className="grp-foot">Your rating is provisional until 20 ranked rounds.</p>
      ) : null}
    </>
  );
}

/** Delete account: the row opens the one confirm sheet, and only its own
 *  Delete calls the server. While that call is out the sheet holds still;
 *  a refusal says why inside it. Closing it gives focus back to the row. */
function DeleteAccount() {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const confirm = () => {
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
  return (
    <>
      <ul className="grp">
        <Row label="Delete account" chevron className="destructive me-delete" onClick={() => setConfirming(true)} />
      </ul>
      {confirming ? (
        <ConfirmSheet title="Delete your account?" line="Your rating and games are deleted." cancel="Cancel"
                      confirm={busy ? "Deleting…" : "Delete"} danger busy={busy} error={error}
                      className="me-delete-confirm" confirmClass="me-delete-yes"
                      onConfirm={confirm} onCancel={() => { setConfirming(false); setError(null); }} />
      ) : null}
    </>
  );
}

/** The iOS app's App Store page; the website lists it under Support, the app does not. */
export const APP_STORE_URL = "https://apps.apple.com/app/id6833598710";

function InfoRows() {
  return (
    <ul className="grp">
      <li><a className="grp-row" href="/privacy" onClick={(e) => followInfoLink(e, "privacy")}>
        <span className="grp-label">Privacy policy</span><span className="grp-value chev" />
      </a></li>
      <li><a className="grp-row" href="/terms" onClick={(e) => followInfoLink(e, "terms")}>
        <span className="grp-label">Terms of use</span><span className="grp-value chev" />
      </a></li>
      <li><a className="grp-row" href="/support" onClick={(e) => followInfoLink(e, "support")}>
        <span className="grp-label">Support</span><span className="grp-value chev" />
      </a></li>
      {isNative() ? null : (
        <li><a className="grp-row me-app-store" href={APP_STORE_URL}>
          <span className="grp-label">On iPhone</span><span className="grp-value chev" />
        </a></li>
      )}
    </ul>
  );
}

/** The settings and the account's rows, beside or under both Stats and
 *  Games. The leaderboard switch
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
  // the app's own account: its name row opens the identity sheet, and it has
  // no Sign out, which would leave it with no way back in
  const device = isUnlinkedDevice(user);
  return (
    <>
      <SettingsGroup />
      <ul className="grp me-account">
        {device ? <Row label={effectiveName(user)} chevron className="me-identity" onClick={() => guestName.open("me_row")} /> : null}
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
        {device ? null : (
          <Row label="Edit name" value={effectiveName(user)} chevron className="me-edit"
               onClick={() => setEditing((v) => !v)}>
            {editing ? <div className="grp-inset"><NameEditForm user={user} onDone={() => setEditing(false)} /></div> : null}
          </Row>
        )}
      </ul>
      <InfoRows />
      {device ? null : (
        <ul className="grp">
          <Row label={signingOut ? "Signing out…" : "Sign out"} className="me-signout" onClick={signOut} />
        </ul>
      )}
      {error ? <div className="lobby-error" role="alert">{error}</div> : null}
      <DeleteAccount />
    </>
  );
}

/** A guest's Me, the signed-in Me minus what only an account has (a
 *  rating, a leaderboard place, saved games): the name they play under with
 *  its initial, one row with that name which opens the identity sheet the
 *  chip opens (the name, and Sign in where it works), the settings and the
 *  help rows. */
function GuestMe() {
  const { name } = useGuestName();
  // a guest who opens Me first gets the same random name Play would give
  useEffect(() => {
    if (!guestName.name.trim()) guestName.fill(randomName());
  }, []);
  const shown = name.trim() || "Guest";
  return (
    <MeColumns
      main={(
        <>
          <div className="me-who">
            <Avatar user={null} size="lg" guestName={shown} />
            <div className="me-who-text">
              <div className="me-name">{shown}</div>
              <div className="me-sub">{GUEST_LINE}</div>
            </div>
          </div>
          <ul className="grp me-account">
            <Row label={shown} chevron className="me-identity" onClick={() => guestName.open("me_row")} />
          </ul>
        </>
      )}
      side={(
        <>
          <SettingsGroup />
          <InfoRows />
        </>
      )}
    />
  );
}

/** Me's two parts: who you are with your stats or games, and the settings.
 *  A wide enough page sets them side by side; otherwise one follows the
 *  other in the one column. */
function MeColumns({ main, side }: { main: ReactNode; side: ReactNode }) {
  return (
    <div className="me-cols">
      <div className="me-col me-main">{main}</div>
      <div className="me-col me-side">{side}</div>
    </div>
  );
}

/** The Me tab, the same at every width: who you are, a Stats / Games
 *  switch over your stats or your saved games, and the settings and the
 *  account's rows beside or below either. Leaving and coming back keeps the
 *  section, the scroll position and the last stats while fresh ones load;
 *  a different viewer or session starts from nothing. */
export default function MePage({ section }: { section: MeSection }) {
  useScreen(section === "games" ? "games" : "me");
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
  else if (!user) {
    body = <GuestMe />;
  }
  else {
    let content: ReactNode;
    if (section === "games") {
      content = <SavedGames onPlay={() => openTab("play")} cacheKey={`${scope}:games`} onReady={markGamesReady}
                             refreshRef={reloadGames} />;
    } else if (res === null) content = <p className="lb-note" role="status">Loading…</p>;
    else if (!res.ok) {
      content = <p className="lobby-error" role="alert">Could not load your stats ({res.status || "no connection"}).</p>;
    } else content = <StatsBody stats={res.data} />;
    body = (
      <Fragment key={scope}>
        <MeColumns
          main={(
            <>
              <Identity user={user} stats={stats} />
              <Segmented label="Show" options={SECTIONS} value={section} onChange={(s) => openTab("me", s)} />
              {content}
            </>
          )}
          side={<Settings user={user} stats={stats} statsKey={statsKey} />}
        />
      </Fragment>
    );
  }
  return (
    <LargeTitlePage className="me-page" scroller={scroller} title="Me"
                    phone={!wide} onRefresh={refresh}>
      {body}
    </LargeTitlePage>
  );
}
