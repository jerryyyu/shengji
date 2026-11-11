import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { auth, deleteAccount, effectiveName, useAuth } from "../auth";
import type { AuthUser } from "../auth";
import { deltaText, fetchStats, setVisibility, signed } from "../ratings/api";
import type { Loaded, MyStats as Stats } from "../ratings/api";
import { openHowto } from "../howto/route";
import { followInfoLink } from "../support/route";
import { Avatar, Segmented } from "../home/HomeShell";
import { EDIT_NAME_EVENT, openTab, takeNameEditRequest } from "../home/route";
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
 *  its own Delete button calls the server. */
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
  if (!confirming) {
    return (
      <ul className="grp">
        <Row label="Delete account" chevron className="destructive me-delete" onClick={() => setConfirming(true)} />
      </ul>
    );
  }
  return (
    <div className="grp me-delete-confirm" role="alertdialog" aria-labelledby="me-delete-title">
      <h3 id="me-delete-title">Delete your account?</h3>
      <p>Your rating, your place on the leaderboard and your saved games are removed for good. This can’t be undone.</p>
      <button type="button" className="btn big danger me-delete-yes" disabled={busy} onClick={confirm}>
        {busy ? "Deleting…" : "Delete account"}
      </button>
      <button type="button" className="btn big subtle me-delete-no" disabled={busy}
              onClick={() => { setConfirming(false); setError(null); }}>
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

function Settings({ user, stats }: { user: AuthUser; stats: Stats | null }) {
  const [visible, setVisible] = useState<boolean | null>(stats?.visible ?? null);
  useEffect(() => { if (stats) setVisible(stats.visible); }, [stats]);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    const open = () => { if (takeNameEditRequest()) setEditing(true); };
    open();
    window.addEventListener(EDIT_NAME_EVENT, open);
    return () => window.removeEventListener(EDIT_NAME_EVENT, open);
  }, []);
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toggle = () => {
    if (visible === null) return;
    setSaving(true);
    setError(null);
    setVisibility(!visible)
      .then((stored) => setVisible(stored))
      .catch((e: Error) => setError(e.message))
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
                  disabled={visible === null || saving} onClick={toggle}>
            <span className="grp-label">Show me on the leaderboard</span>
            <span className={`ios-switch${visible ? " on" : ""}`} aria-hidden="true" />
          </button>
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
          <button type="button" className="apple-signin" disabled aria-describedby="apple-soon">
            Sign in with Apple
          </button>
          <p className="signin-foot" id="apple-soon">Coming soon</p>
        </div>
      ) : null}
      <InfoRows />
    </>
  );
}

/** The Me tab: who you are, your stats or your saved games, and the
 *  account's settings. */
export default function MePage({ section, onBack }: { section: MeSection; onBack?: () => void }) {
  const account = useAuth();
  const user = account.status === "in" ? account.user : null;
  const [res, setRes] = useState<Loaded<Stats> | null>(null);
  useEffect(() => {
    if (!user) return;
    let live = true;
    fetchStats().then((r) => { if (live) setRes(r); });
    return () => { live = false; };
  }, [user]);
  const stats = res && res.ok ? res.data : null;

  let body: ReactNode;
  if (account.status === "loading") body = <p className="lb-note" role="status">Loading…</p>;
  else if (!user) body = <GuestMe clientId={account.status === "out" ? account.clientId : null} />;
  else {
    let content: ReactNode;
    if (section === "games") content = <SavedGames onPlay={() => openTab("play")} />;
    else if (res === null) content = <p className="lb-note" role="status">Loading…</p>;
    else if (!res.ok) {
      content = <p className="lobby-error" role="alert">Could not load your stats ({res.status || "no connection"}).</p>;
    } else content = <StatsBody stats={res.data} />;
    body = (
      <>
        <Identity user={user} stats={stats} />
        <Segmented label="Show" options={SECTIONS} value={section} onChange={(s) => openTab("me", s)} />
        {content}
        {section === "stats" ? <Settings user={user} stats={stats} /> : null}
      </>
    );
  }
  return (
    <div className="screen home-page me-page">
      <div className="home-col">
        {onBack ? <button className="btn subtle games-back home-back" onClick={onBack}>‹ Back to game</button> : null}
        <h1 className="large-title">Me</h1>
        {body}
      </div>
    </div>
  );
}
