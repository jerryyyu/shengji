import type { ReactNode } from "react";
import { useAuth } from "../auth";
import { navigate } from "../replay/route";
import { guestName } from "../guestName";
import { useT } from "../i18n";

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

/** A 401 from the history API: the session is gone (or never was). Sign in
 *  opens the identity sheet. */
export function SignInPrompt() {
  const account = useAuth();
  const t = useT();
  return (
    <GamesNotice title={t("me.games.signInLine")}>
      {account.status === "out" && account.clientId ? (
        <button type="button" className="btn gold big games-cta" onClick={() => guestName.open("lapsed")}>{t("me.signIn")}</button>
      ) : null}
    </GamesNotice>
  );
}

/** A 404: not this account's game or round, or it was removed. */
export function GamesUnavailable() {
  const t = useT();
  return (
    <GamesNotice title={t("me.games.unavailable")}>
      <button className="btn big games-cta" onClick={() => navigate({ page: "list" })}>{t("me.games.myGames")}</button>
    </GamesNotice>
  );
}
