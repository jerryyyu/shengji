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
        gis.renderButton(slot.current, {
          theme: "filled_black", size: "medium", shape: "pill", text: "signin_with", logo_alignment: "left",
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
