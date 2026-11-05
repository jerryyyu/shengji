import { useAuth } from "../auth";
import { navigate } from "../replay/route";
import GoogleSignIn from "./GoogleSignIn";

/** A 401 from the history API: the session is gone (or never was). */
export function SignInPrompt() {
  const account = useAuth();
  return (
    <div className="games-status" role="status">
      <p>Sign in to see your saved games.</p>
      {account.status === "out" && account.clientId ? <GoogleSignIn clientId={account.clientId} /> : null}
    </div>
  );
}

/** A 404: not this account's game or round, or it was removed. */
export function GamesUnavailable() {
  return (
    <div className="games-status" role="status">
      <p>This game isn't available.</p>
      <button className="btn" onClick={() => navigate({ page: "list" })}>My games</button>
    </div>
  );
}
