import type { ReactNode } from "react";
import { useAuth } from "../auth";
import { navigate } from "../replay/route";
import GoogleSignIn from "./GoogleSignIn";

/** The header every My games page shares: a back control above a centred
 *  title and subtitle, on the lobby's type scale. */
export function GamesHead({ back, onBack, title, sub }: {
  back: string; onBack: () => void; title: string; sub?: ReactNode;
}) {
  return (
    <header className="games-head">
      <button className="btn subtle games-back" onClick={onBack}>‹ {back}</button>
      <h2 className="games-title">{title}</h2>
      {sub ? <p className="game-subtitle games-sub">{sub}</p> : null}
    </header>
  );
}

/** A centred message that fills the panel body: loading, empty and error states. */
export function GamesNotice({ title, children }: { title?: string; children?: ReactNode }) {
  return (
    <div className="games-status" role="status">
      {title ? <p className="games-status-title">{title}</p> : null}
      {children}
    </div>
  );
}

/** A 401 from the history API: the session is gone (or never was). */
export function SignInPrompt() {
  const account = useAuth();
  return (
    <GamesNotice title="Sign in to see your saved games.">
      {account.status === "out" && account.clientId ? <GoogleSignIn clientId={account.clientId} /> : null}
    </GamesNotice>
  );
}

/** A 404: not this account's game or round, or it was removed. */
export function GamesUnavailable() {
  return (
    <GamesNotice title="This game isn't available.">
      <p>It may have been removed from your history.</p>
      <button className="btn big games-cta" onClick={() => navigate({ page: "list" })}>My games</button>
    </GamesNotice>
  );
}
