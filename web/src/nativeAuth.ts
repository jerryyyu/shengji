// Google and Apple sign-in inside the iOS app.
//
// Google refuses its web sign-in (the GIS button's iframe and popup) inside an
// embedded WebView, so in the app the page asks the shell's SocialLogin plugin
// for an ID token instead. The token is posted to the same login endpoint as
// the website's; the server accepts it because it lists the iOS client id.
//
// Like src/native.ts, nothing here imports a Capacitor package: the plugin is
// reached by name through the bridge the shell injects. An older app build
// that predates the plugin reports it unavailable, and the page then shows no
// sign-in button at all rather than one that cannot work.
//
// Sign in with Apple uses the same plugin's native Apple sheet. It is offered
// only on iOS and only by a shell whose plugin has the Apple provider enabled:
// an earlier build refuses the Apple initialisation, and the page then shows
// the Google button alone.

import { isNative } from "./native";

/** The iOS OAuth client of the app. Public by design, like the web one. */
export const IOS_GOOGLE_CLIENT_ID =
  "804081879262-2d30sq582hrq4oiae6b93slnu6qj6otp.apps.googleusercontent.com";

export const PLUGIN = "SocialLogin";

type Method = (opts?: Record<string, unknown>) => Promise<unknown>;

interface Bridge {
  getPlatform?: () => string;
  isPluginAvailable?: (name: string) => boolean;
  registerPlugin?: (name: string) => Record<string, Method | undefined>;
  Plugins?: Record<string, Record<string, Method | undefined> | undefined>;
}

function bridge(): Bridge | null {
  if (!isNative()) return null;
  return (window as unknown as { Capacitor?: Bridge }).Capacitor ?? null;
}

/** True only in an app build whose shell carries the plugin. */
export function nativeGoogleAvailable(): boolean {
  const cap = bridge();
  if (!cap) return false;
  try {
    if (typeof cap.isPluginAvailable === "function") return cap.isPluginAvailable(PLUGIN);
    return Boolean(cap.Plugins?.[PLUGIN]);
  } catch {
    return false;
  }
}

function method(name: string, provider = "Google"): Method {
  const cap = bridge();
  const proxy = cap?.registerPlugin?.(PLUGIN) ?? cap?.Plugins?.[PLUGIN];
  const fn = proxy?.[name];
  if (typeof fn !== "function") throw new Error(`${provider} sign-in is not available in this app version.`);
  return fn;
}

/** The player closed Google's sheet; nothing to report. */
export class SignInCancelled extends Error {
  constructor() {
    super("Sign-in cancelled.");
  }
}

let initialised: string | null = null;

/** Opens Google's native sign-in sheet and resolves with its ID token.
 *
 *  `webClientId` (from `/api/auth/config`) is passed as the server client, so
 *  Google mints the token for the website's audience; the server also accepts
 *  the iOS client id as an audience. `nonce` goes into the token, and the
 *  server checks it against what the page posts, exactly as on the web. */
export async function nativeGoogleCredential(webClientId: string, nonce: string): Promise<string> {
  if (initialised !== webClientId) {
    await method("initialize")({
      google: { iOSClientId: IOS_GOOGLE_CLIENT_ID, iOSServerClientId: webClientId, mode: "online" },
    });
    initialised = webClientId;
  }
  let resp: unknown;
  try {
    resp = await method("login")({
      provider: "google",
      options: { scopes: ["email", "profile"], nonce },
    });
  } catch (e) {
    const err = e as { code?: string; message?: string };
    if (err?.code === "USER_CANCELLED" || /cancel/i.test(err?.message ?? "")) throw new SignInCancelled();
    throw new Error(err?.message || "Google sign-in failed.");
  }
  const token = (resp as { result?: { idToken?: string | null } } | undefined)?.result?.idToken;
  if (!token) throw new Error("Google sign-in returned no ID token.");
  return token;
}

/** Forget the Google account on the device, so the next sign-in offers the
 *  account picker. Best effort: the server session is already revoked. */
export async function nativeGoogleSignOut(): Promise<void> {
  if (!nativeGoogleAvailable()) return;
  try {
    await method("logout")({ provider: "google" });
  } catch {
    /* nothing signed in on the device */
  }
}

function isIos(): boolean {
  try {
    return bridge()?.getPlatform?.() === "ios";
  } catch {
    return false;
  }
}

let appleReady: Promise<boolean> | null = null;

/** Resolves true when this app build can run Sign in with Apple: iOS, the
 *  plugin present, and its Apple provider enabled (the initialisation, which
 *  asks for the authorization code to be returned untouched, succeeds). Asked
 *  once per page; a refusal is remembered as "no Apple button". */
export function nativeAppleReady(): Promise<boolean> {
  if (!isIos() || !nativeGoogleAvailable()) return Promise.resolve(false);
  if (!appleReady) {
    appleReady = (async () => {
      try {
        await method("initialize", "Apple")({ apple: { useProperTokenExchange: true, redirectUrl: "" } });
        return true;
      } catch {
        return false;
      }
    })();
  }
  return appleReady;
}

/** What Apple's sheet returned. The names are filled only on the first
 *  authorization of this app by this Apple ID (the plugin may also replay a
 *  name it kept on the device); empty strings become null. */
export interface AppleCredential {
  identityToken: string;
  authorizationCode: string | null;
  givenName: string | null;
  familyName: string | null;
}

/** Opens Apple's native sheet. `nonceDigest` (the SHA-256 hex of the raw
 *  nonce the page keeps) becomes the token's `nonce` claim; the server checks
 *  it against the raw nonce the page posts. */
export async function nativeAppleCredential(nonceDigest: string): Promise<AppleCredential> {
  if (!(await nativeAppleReady())) throw new Error("Sign in with Apple is not available in this app version.");
  let resp: unknown;
  try {
    resp = await method("login", "Apple")({ provider: "apple", options: { nonce: nonceDigest } });
  } catch (e) {
    const err = e as { code?: string; message?: string };
    // ASAuthorizationError.canceled is code 1001.
    if (err?.code === "USER_CANCELLED" || /cancel|1001/i.test(err?.message ?? "")) throw new SignInCancelled();
    throw new Error(err?.message || "Sign in with Apple failed.");
  }
  const result = (resp as {
    result?: {
      idToken?: string | null;
      authorizationCode?: string | null;
      profile?: { givenName?: string | null; familyName?: string | null };
    };
  } | undefined)?.result;
  const identityToken = result?.idToken;
  if (!identityToken) throw new Error("Sign in with Apple returned no identity token.");
  const orNull = (v: string | null | undefined) => (v ? v : null);
  return {
    identityToken,
    authorizationCode: orNull(result?.authorizationCode),
    givenName: orNull(result?.profile?.givenName),
    familyName: orNull(result?.profile?.familyName),
  };
}

/** Forget the Apple sign-in on the device; with `clearName` also the name the
 *  plugin keeps, as on account deletion. Best effort, like Google's. */
export async function nativeAppleSignOut(clearName: boolean): Promise<void> {
  if (!isIos() || !nativeGoogleAvailable()) return;
  try {
    await method("logout", "Apple")({ provider: "apple", clearCachedUserInfo: clearName });
  } catch {
    /* nothing signed in on the device, or no Apple provider in this build */
  }
}

/** Test hook: forget the plugin initialisation. */
export function resetNativeAuthForTests(): void {
  initialised = null;
  appleReady = null;
}
