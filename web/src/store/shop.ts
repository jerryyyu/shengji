// The store's state and its purchases. The store (the Collection's More
// companions and Restore purchases) is shown only where it can sell: in an
// app build with the StoreKit plugin, to an account the server turned the
// store on for (`features.store`), and never on the China mainland
// storefront. Every purchase is Apple's signed transaction handed to
// the server (`verifyPurchase`); the account the server then reports is what
// the page shows as owned.
import { useEffect, useState } from "react";
import { auth, useAuth, verifyPurchase } from "../auth";
import type { AuthUser } from "../auth";
import { COMPANION_PRODUCTS } from "../companion/look";
import { refreshAccount } from "../companion/writes";
import { viewerScope } from "../home/session";
import type { MessageKey } from "../i18n";
import { haptic } from "../native";
import {
  onStoreTransaction, storeFinish, storeKitAvailable, storePending, storeProducts, storePurchase, storeRestore,
  storeStorefront,
} from "./storeKit";
import type { SignedTransaction } from "./storeKit";

/** The storefront that sells nothing. */
export const NO_SALES_STOREFRONT = "CHN";

/** The App Store products the store sells. */
export const SOLD_PRODUCTS = Object.values(COMPANION_PRODUCTS).filter((p): p is string => !!p);

let storefront: string | null = null;

const signedIn = (): AuthUser | null => (auth.state.status === "in" ? auth.state.user : null);

/** Whether the account and this build may show the store (the storefront
 *  aside, which `useShop` reads from the store). */
export function shopAllowed(user: AuthUser | null | undefined): boolean {
  return !!user && user.features?.store === true && storeKitAvailable();
}

/** The refusals no later presentation can turn into a grant (the server's
 *  `purchases.PERMANENT_REFUSALS`): another account holds it (the payer, once
 *  the server gave it to them), it was refunded, or it is another app's.
 *  Only after one of these, or a grant, is a transaction acknowledged. Every
 *  other refusal (`unknown_token`, a check that depends on the storefront or
 *  the environment, a product not sold yet, no session, the store off, no
 *  network, a 5xx) leaves it with the App Store, which hands it over again. */
export const PERMANENT_REFUSALS = new Set(["held_by_other", "revoked", "wrong_app"]);

/** What the store's one status line says for a refusal, in place of its
 *  code: Apple charged and the server has not answered yet (`received`),
 *  another account holds it (where to use it), it was refunded, else
 *  the purchase or the restore did not complete. Null when the account has
 *  no session to buy with (`sign_in_required`, 401): the answer is the
 *  sign-in flow, not a line. */
export function refusalMessage(err: unknown, during: "buy" | "restore"): MessageKey | null {
  const e = err as { reason?: unknown; status?: unknown };
  if (e?.reason === "sign_in_required" || e?.status === 401) return null;
  if ((err as { received?: unknown })?.received === true) return "home.shopReceived";
  if (e?.reason === "held_by_other") return "home.shopHeldByOther";
  if (e?.reason === "revoked") return "home.shopRefunded";
  return during === "buy" ? "home.shopFailed" : "home.restoreFailed";
}

const isPermanent = (err: unknown) => PERMANENT_REFUSALS.has((err as { reason?: string })?.reason ?? "");

// One delivery at a time: each is verified and acknowledged in turn, and the
// account is then read again (`refreshAccount`, whose latest read wins), so
// an older answer never replaces a newer one.
let chain: Promise<unknown> = Promise.resolve();
function serial<T>(task: () => Promise<T>): Promise<T> {
  const next = chain.then(task, task);
  chain = next.catch(() => {});
  return next;
}

/** Deliver a transaction to the server and acknowledge it to the App Store
 *  once the server has settled it (a grant, or a permanent refusal).
 *  Resolves with the products the server confirmed for the presenting
 *  session, or null when there is no session to present it; rejects with
 *  the refusal (`reason`, `status`). The account is read again afterwards. */
function deliver(t: SignedTransaction): Promise<string[] | null> {
  return serial(async () => {
    if (!signedIn()) return null;
    try {
      const user = await verifyPurchase(t.jws, storefront);
      if (t.transactionId) await storeFinish(t.transactionId).catch(() => {});
      return user.products ?? [];
    } catch (err) {
      if (t.transactionId && isPermanent(err)) await storeFinish(t.transactionId).catch(() => {});
      throw err;
    } finally {
      await refreshAccount().catch(() => null);
    }
  });
}

/** A refusal the same hand-over may pass in a moment: no answer (no
 *  network), too many requests, or a 5xx. */
const isTransient = (err: unknown) => {
  const s = (err as { status?: unknown })?.status;
  return typeof s !== "number" || s === 0 || s === 429 || s >= 500;
};

/** Hand the server every transaction the App Store still holds unfinished;
 *  how many met a transient refusal. */
async function recoverPending(): Promise<number> {
  const list = await storePending().catch(() => []);
  let transient = 0;
  for (const t of list) await deliver(t).catch((err: unknown) => { if (isTransient(err)) transient += 1; });
  return transient;
}

/** The first and the longest wait between hand-overs of a purchase Apple
 *  charged for while the server could not be reached. */
export const RETRY_FIRST_MS = 2000;
export const RETRY_MAX_MS = 30000;

// A purchase charged while the server was out of reach: the shown store
// hands the App Store's unfinished transactions over again until it lands.
let awaiting = false;
const awaitingListeners = new Set<() => void>();
function awaitDelivery() {
  awaiting = true;
  awaitingListeners.forEach((f) => f());
}

export type BuyOutcome = "owned" | "cancelled" | "pending" | "none";

/** A payer token as the server issues it (a UUID). */
export const isPayerToken = (token: unknown): token is string =>
  typeof token === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(token);

/** Buy `product` for the signed-in account. The account's `store_token` is
 *  bound to the purchase before Apple's sheet opens, so Apple signs which
 *  account paid and the server grants it to that account whoever presents
 *  it; without a valid token the sheet is never opened ("none"). Resolves
 *  "owned" only when the server confirmed the grant to the same session that
 *  opened the sheet; "none" when the session changed meanwhile (the payer
 *  still gets it); rejects with the refusal. */
export async function buy(product: string): Promise<BuyOutcome> {
  const payer = signedIn();
  if (!payer || !isPayerToken(payer.store_token)) return "none";
  const scope = viewerScope(auth.state);
  const result = await storePurchase(product, payer.store_token);
  if (result.status === "cancelled" || result.status === "pending") return result.status;
  if (result.status !== "purchased") throw Object.assign(new Error("unverified"), { status: 0 });
  const { jws, productId, transactionId } = result;
  const same = () => viewerScope(auth.state) === scope && !!signedIn();
  let granted: string[] | null;
  try {
    granted = await deliver({ jws, productId, ...(transactionId ? { transactionId } : {}) });
  } catch (err) {
    if (!same()) return "none";
    if (isTransient(err)) {
      // Apple charged; the transaction stays unfinished and is handed over again
      awaitDelivery();
      throw Object.assign(err instanceof Error ? err : new Error("verify"), { received: true });
    }
    throw err;
  }
  if (!same() || !granted?.includes(product)) return "none";
  haptic("won");
  return "owned";
}

/** Restore purchases: everything the Apple account owns, verified again.
 *  A permanent refusal is settled (acknowledged) and a refusal that may pass
 *  later keeps its transaction. Once every transaction has been tried, it
 *  rejects with the first refusal that may pass later; else resolves when
 *  any was restored onto the account (its tile says so); else, when every
 *  one was refused for good, rejects with that refusal, another account's
 *  hold before a refund before any other, so the line says why nothing
 *  arrived. Nothing found resolves. */
export async function restorePurchases(): Promise<void> {
  const list = await storeRestore();
  let retry: unknown = null;
  let restored = false;
  const refused: unknown[] = [];
  for (const t of list) {
    await deliver(t).then(
      (granted) => { if (granted?.includes(t.productId)) restored = true; },
      (err: unknown) => {
        if (!isPermanent(err)) retry ??= err;
        else refused.push(err);
      });
  }
  if (retry !== null) throw retry;
  if (restored || refused.length === 0) return;
  const kind = (reason: string) => refused.find((e) => (e as { reason?: string }).reason === reason);
  throw kind("held_by_other") ?? kind("revoked") ?? refused[0];
}

/** Whether the account must sign in with Apple or Google before it buys or
 *  restores: the app's own device account. Restoring onto it would bind the
 *  purchases to an account only this device knows. */
export function useSignInFirst(): boolean {
  const account = useAuth();
  return account.status === "in" && account.user?.linked === false;
}

export interface ShopState {
  /** The store may be shown. */
  shown: boolean;
  /** StoreKit's localized price per product, once it answers. */
  prices: Record<string, string>;
  /** Whether `shown` is final: false while an account the store may be
   *  shown to waits for the App Store's storefront. */
  settled: boolean;
}

/** The store's visibility and prices for the signed-in account; while it is
 *  shown, transactions the App Store delivers outside a purchase (Ask to
 *  Buy approved, a purchase on another device) are verified as they come,
 *  and any the App Store still holds unfinished are handed over again. */
export function useShop(): ShopState {
  const account = useAuth();
  const user = account.status === "in" ? account.user : null;
  const allowed = shopAllowed(user);
  const [state, setState] = useState<ShopState>({ shown: false, prices: {}, settled: false });
  useEffect(() => {
    if (!allowed) {
      setState({ shown: false, prices: {}, settled: false });
      return;
    }
    setState({ shown: false, prices: {}, settled: false });
    let live = true;
    void (async () => {
      storefront = await storeStorefront();
      if (!live) return;
      if (storefront === NO_SALES_STOREFRONT) {
        setState({ shown: false, prices: {}, settled: true });
        return;
      }
      setState((s) => ({ ...s, shown: true, settled: true }));
      const found = await storeProducts(SOLD_PRODUCTS).catch(() => []);
      if (live) setState({ shown: true, prices: Object.fromEntries(found.map((p) => [p.id, p.displayPrice])), settled: true });
    })();
    const off = onStoreTransaction((t) => { void deliver(t).catch(() => null); });
    return () => { live = false; off(); };
  }, [allowed]);
  // The App Store's unfinished transactions go to the server whenever the
  // account that would receive them changes while the store is shown: on
  // opening, and in place when a device account signs in (same store access,
  // new identity and token), so an approved purchase lands without leaving
  // the page.
  const eligible = state.shown && !!user && user.linked !== false;
  const payer = eligible ? `${user?.email ?? ""}|${user?.store_token ?? ""}` : null;
  useEffect(() => {
    if (state.shown) void recoverPending();
  }, [state.shown, payer]);
  // A received purchase is handed over again on a doubling wait while the
  // store is shown, and at once when the network comes back.
  useEffect(() => {
    if (!state.shown) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let wait = RETRY_FIRST_MS;
    let running = false;
    const attempt = async () => {
      timer = undefined;
      if (!live || !awaiting || running) return;
      running = true;
      const left = await recoverPending().finally(() => { running = false; });
      if (!live) return;
      if (left === 0) {
        awaiting = false;
        return;
      }
      timer = setTimeout(() => { void attempt(); }, wait);
      wait = Math.min(wait * 2, RETRY_MAX_MS);
    };
    const schedule = () => {
      if (timer !== undefined) clearTimeout(timer);
      wait = RETRY_FIRST_MS;
      timer = setTimeout(() => { void attempt(); }, wait);
      wait = Math.min(wait * 2, RETRY_MAX_MS);
    };
    const now = () => {
      if (timer !== undefined) clearTimeout(timer);
      wait = RETRY_FIRST_MS;
      void attempt();
    };
    awaitingListeners.add(schedule);
    window.addEventListener("online", now);
    if (awaiting) schedule();
    return () => {
      live = false;
      if (timer !== undefined) clearTimeout(timer);
      awaitingListeners.delete(schedule);
      window.removeEventListener("online", now);
    };
  }, [state.shown]);
  // an account the store is never shown to is settled at once
  return allowed ? state : { shown: false, prices: {}, settled: true };
}
