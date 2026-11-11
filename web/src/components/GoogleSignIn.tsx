import { useEffect, useRef, useState, type CSSProperties } from "react";
import { auth, loadGis, loginWithGoogle, newNonce } from "../auth";
import { isNative } from "../native";
import { nativeGoogleAvailable, nativeGoogleCredential, SignInCancelled } from "../nativeAuth";

/** The "Sign in with Google" button. Rendered only when the server advertised
 *  a client id. On the website it is the official GIS button, whose script is
 *  fetched the first time this mounts; in the iOS app, where Google refuses
 *  that button, it is a native sign-in through the shell. */
export default function GoogleSignIn({ clientId }: { clientId: string }) {
  if (isNative()) return <NativeGoogleSignIn clientId={clientId} />;
  return <WebGoogleSignIn clientId={clientId} />;
}

function WebGoogleSignIn({ clientId }: { clientId: string }) {
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

// Google's dark "filled_black" pill, matching the website's GIS button.
const NATIVE_BUTTON: CSSProperties = {
  display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
  width: "100%", maxWidth: 400, minHeight: 44, padding: "0 16px",
  borderRadius: 999, border: "1px solid #8e918f", background: "#131314", color: "#e3e3e3",
  font: "500 15px/1 Roboto, system-ui, -apple-system, sans-serif", cursor: "pointer",
};

function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

/** The app's sign-in: Google's native sheet hands back an ID token, which is
 *  posted to the same endpoint as the website's credential. An app build
 *  without the plugin gets a note instead of a button that cannot work. */
function NativeGoogleSignIn({ clientId }: { clientId: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!nativeGoogleAvailable()) {
    return (
      <div className="google-signin">
        <p className="signin-upsell" data-testid="google-signin-unavailable">
          Update the app to sign in.
        </p>
      </div>
    );
  }

  const signIn = async () => {
    setBusy(true);
    setError(null);
    const nonce = newNonce();
    try {
      const credential = await nativeGoogleCredential(clientId, nonce);
      auth.signedIn(await loginWithGoogle(credential, nonce));
    } catch (e) {
      if (!(e instanceof SignInCancelled)) setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="google-signin">
      <button type="button" className="google-signin-native" data-testid="google-signin" style={NATIVE_BUTTON}
              disabled={busy} onClick={() => void signIn()}>
        <GoogleMark />
        <span>Continue with Google</span>
      </button>
      {error ? <div className="lobby-error">{error}</div> : null}
    </div>
  );
}
