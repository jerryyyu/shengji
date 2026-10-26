import { useEffect, useRef, useState } from "react";
import { auth, loadGis, loginWithGoogle, newNonce } from "../auth";

/** The official "Sign in with Google" button. Rendered only when the server
 *  advertised a client id; the GIS script is fetched the first time this
 *  mounts, never for a deployment with the feature off. */
export default function GoogleSignIn({ clientId }: { clientId: string }) {
  const slot = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const nonce = newNonce();
    loadGis()
      .then((gis) => {
        if (cancelled || !slot.current) return;
        gis.initialize({
          client_id: clientId,
          nonce,
          ux_mode: "popup",
          itp_support: true,
          callback: ({ credential }) => {
            loginWithGoogle(credential, nonce)
              .then((user) => auth.signedIn(user))
              .catch((e: Error) => setError(e.message));
          },
        });
        slot.current.replaceChildren();
        // Full width of the lobby column, as the other buttons are; GIS caps the width at 400px.
        const width = Math.min(400, Math.max(200, Math.round(slot.current.getBoundingClientRect().width)));
        gis.renderButton(slot.current, {
          theme: "filled_black", size: "large", shape: "pill", text: "continue_with", logo_alignment: "center", width,
        });
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [clientId]);

  return (
    <div className="google-signin">
      <div ref={slot} className="google-signin-slot" data-testid="google-signin" />
      {error ? <div className="lobby-error">{error}</div> : null}
    </div>
  );
}
