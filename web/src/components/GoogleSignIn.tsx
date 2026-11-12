import { useEffect, useRef, useState, type CSSProperties } from "react";
import { auth, loadGis, loginWithApple, loginWithGoogle, newNonce, sha256Hex } from "../auth";
import { isNative } from "../native";
import {
  nativeAppleCredential, nativeAppleReady, nativeGoogleAvailable, nativeGoogleCredential, SignInCancelled,
} from "../nativeAuth";

/** The "Sign in with Google" button. Rendered only when the server advertised
 *  a client id. On the website it is the official GIS button, whose script is
 *  fetched the first time this mounts; in the iOS app, where Google refuses
 *  that button, it is a native sign-in through the shell, with "Sign in with
 *  Apple" beside it when the shell supports it. */
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

// Apple's black "Sign in with Apple" button, in the Google button's pill and
// outline so the two read as equals on the charcoal felt.
const APPLE_BUTTON: CSSProperties = {
  ...NATIVE_BUTTON, gap: 8, background: "#000", color: "#fff",
  font: "500 16px/1 -apple-system, system-ui, sans-serif",
};

function AppleMark() {
  return (
    <svg width="16" height="19" viewBox="0 0 814 1000" aria-hidden="true" fill="currentColor">
      <path d="M788.1 340.9c-5.8 4.5-108.2 62.2-108.2 190.5 0 148.4 130.3 200.9 134.2 202.2-.6 3.2-20.7 71.9-68.7 141.9-42.8 61.6-87.5 123.1-155.5 123.1s-85.5-39.5-164-39.5c-76.5 0-103.7 40.8-165.9 40.8s-105.6-57-155.5-127C46.7 790.7 0 663 0 541.8c0-194.4 126.4-297.5 250.8-297.5 66.1 0 121.2 43.4 162.7 43.4 39.5 0 101.1-46 176.3-46 28.5 0 130.9 2.6 198.3 99.2zm-234-181.5c31.1-36.9 53.1-88.1 53.1-139.3 0-7.1-.6-14.3-1.9-20.1-50.6 1.9-110.8 33.7-147.1 75.8-28.5 32.4-55.1 83.6-55.1 135.5 0 7.8 1.3 15.6 1.9 18.1 3.2.6 8.4 1.3 13.6 1.3 45.4 0 102.5-30.4 135.5-71.3z" />
    </svg>
  );
}

/** The app's sign-in: Google's native sheet hands back an ID token, which is
 *  posted to the same endpoint as the website's credential; Apple's sheet
 *  hands back an identity token and an authorization code for the Apple
 *  endpoint. An app build without the plugin gets a note instead of buttons
 *  that cannot work. */
function NativeGoogleSignIn({ clientId }: { clientId: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [apple, setApple] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void nativeAppleReady().then((ready) => {
      if (!cancelled) setApple(ready);
    });
    return () => {
      cancelled = true;
    };
  }, []);

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

  const signInWithApple = async () => {
    setBusy(true);
    setError(null);
    const nonce = newNonce();
    try {
      const cred = await nativeAppleCredential(await sha256Hex(nonce));
      auth.signedIn(await loginWithApple({
        identityToken: cred.identityToken,
        nonce,
        authorizationCode: cred.authorizationCode,
        givenName: cred.givenName,
        familyName: cred.familyName,
      }));
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
      {apple ? (
        <button type="button" className="apple-signin-native" data-testid="apple-signin" style={APPLE_BUTTON}
                disabled={busy} onClick={() => void signInWithApple()}>
          <AppleMark />
          <span>Sign in with Apple</span>
        </button>
      ) : null}
      {error ? <div className="lobby-error">{error}</div> : null}
    </div>
  );
}
