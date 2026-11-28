// In-app purchases through the shell's ShengjiStore plugin (StorePlugin.swift,
// StoreKit 2). Like src/keychain.ts, nothing here imports a Capacitor package:
// the plugin is reached by name through the bridge the shell injects. In a
// browser, and in an app build that predates the plugin, there is no store:
// `storeKitAvailable()` is false and the Shop is not shown.
//
// The plugin hands over each purchase as Apple's signed transaction (a JWS);
// only the server's verification of it (`verifyPurchase`) changes what an
// account owns. The App Store keeps a transaction unfinished, and hands it
// over again (`storePending`), until `storeFinish` acknowledges it.

import { isNative } from "../native";

export const STORE_PLUGIN = "ShengjiStore";

type Method = (opts?: Record<string, unknown>) => Promise<unknown>;
type Listen = (event: string, cb: (data: unknown) => void) => Promise<{ remove?: () => unknown }> | { remove?: () => unknown };

interface Bridge {
  isPluginAvailable?: (name: string) => boolean;
  registerPlugin?: (name: string) => Record<string, Method | Listen | undefined>;
  Plugins?: Record<string, Record<string, Method | Listen | undefined> | undefined>;
}

function proxy(): Record<string, Method | Listen | undefined> | null {
  if (!isNative()) return null;
  const cap = (window as unknown as { Capacitor?: Bridge }).Capacitor;
  if (!cap) return null;
  try {
    if (typeof cap.isPluginAvailable === "function" && !cap.isPluginAvailable(STORE_PLUGIN)) return null;
    return cap.registerPlugin?.(STORE_PLUGIN) ?? cap.Plugins?.[STORE_PLUGIN] ?? null;
  } catch {
    return null;
  }
}

function method(name: "products" | "purchase" | "restore" | "entitlements" | "storefront" | "pending" | "finish"): Method | null {
  const fn = proxy()?.[name];
  return typeof fn === "function" ? (fn as Method) : null;
}

/** True only in an app build whose shell carries the plugin. */
export function storeKitAvailable(): boolean {
  return method("purchase") !== null;
}

export interface StoreProduct {
  id: string;
  displayName: string;
  /** StoreKit's own localized price, shown as it comes. */
  displayPrice: string;
}

export interface SignedTransaction {
  jws: string;
  productId: string;
  /** The App Store's id, which `storeFinish` acknowledges; absent from a
   *  shell that finishes on its own. */
  transactionId?: string;
  /** StoreKit could not verify it on the device: the server's own check of
   *  `jws` decides, and only its grant finishes it. */
  unverified?: true;
}

export type PurchaseResult =
  | ({ status: "purchased" } & SignedTransaction)
  | ({ status: "unverified" } & SignedTransaction)
  | { status: "cancelled" | "pending" | "unverified" };

const isSigned = (t: unknown): t is SignedTransaction =>
  typeof (t as SignedTransaction)?.jws === "string" && typeof (t as SignedTransaction)?.productId === "string";

const signed = (t: SignedTransaction): SignedTransaction => ({
  jws: t.jws, productId: t.productId,
  ...(typeof t.transactionId === "string" && t.transactionId ? { transactionId: t.transactionId } : {}),
  ...(t.unverified === true ? { unverified: true as const } : {}),
});

/** The App Store's products among `ids`, in that order; none without a store. */
export async function storeProducts(ids: readonly string[]): Promise<StoreProduct[]> {
  const fn = method("products");
  if (!fn) return [];
  const r = (await fn({ ids: [...ids] })) as { products?: unknown } | undefined;
  const list = Array.isArray(r?.products) ? r.products : [];
  return list.filter((p): p is StoreProduct =>
    typeof p?.id === "string" && typeof p?.displayName === "string" && typeof p?.displayPrice === "string");
}

/** Apple's purchase sheet for `id`, bound to the paying account's
 *  `appAccountToken` when given. Rejects when there is no store. */
export async function storePurchase(id: string, appAccountToken: string | null = null): Promise<PurchaseResult> {
  const fn = method("purchase");
  if (!fn) throw new Error("no store");
  const r = (await fn(appAccountToken ? { id, appAccountToken } : { id })) as { status?: unknown; jws?: unknown; productId?: unknown } | undefined;
  if (r?.status === "purchased" && isSigned(r)) return { status: "purchased", ...signed(r) };
  if (r?.status === "cancelled" || r?.status === "pending") return { status: r.status };
  // a shell that hands over an unverified purchase sends its JWS, flagged
  if (r?.status === "unverified" && isSigned(r)) return { status: "unverified", ...signed(r), unverified: true };
  return { status: "unverified" };
}

async function signedList(name: "restore" | "entitlements" | "pending"): Promise<SignedTransaction[]> {
  const fn = method(name);
  if (!fn) return [];
  const r = (await fn()) as { transactions?: unknown } | undefined;
  return (Array.isArray(r?.transactions) ? r.transactions : []).filter(isSigned).map(signed);
}

/** Every transaction the App Store holds unfinished: handed over before and
 *  not yet acknowledged, so the server may not have it. */
export const storePending = () => signedList("pending");

/** Acknowledge a transaction the server has settled; the App Store then
 *  stops handing it over. A no-op without a store. */
export async function storeFinish(transactionId: string): Promise<void> {
  const fn = method("finish");
  if (fn) await fn({ transactionId });
}

/** Restore purchases: syncs with the App Store (it may ask the player to
 *  sign in to their Apple account), then lists what the Apple account owns. */
export const storeRestore = () => signedList("restore");

/** What the Apple account owns, without asking anything of the player. */
export const storeEntitlements = () => signedList("entitlements");

/** The App Store storefront's country (ISO 3166-1 alpha-3, `CHN` for China
 *  mainland), or null when the store cannot say. */
export async function storeStorefront(): Promise<string | null> {
  const fn = method("storefront");
  if (!fn) return null;
  try {
    const r = (await fn()) as { countryCode?: unknown } | undefined;
    return typeof r?.countryCode === "string" ? r.countryCode.toUpperCase() : null;
  } catch {
    return null;
  }
}

/** Call `cb` for each transaction the App Store delivers outside a purchase
 *  (Ask to Buy approved, another device, a refund). Returns the unsubscribe. */
export function onStoreTransaction(cb: (t: SignedTransaction) => void): () => void {
  const add = proxy()?.addListener;
  if (typeof add !== "function") return () => {};
  let handle: { remove?: () => unknown } | null = null;
  let gone = false;
  Promise.resolve((add as Listen)("transaction", (data) => { if (isSigned(data)) cb(signed(data)); }))
    .then((h) => { handle = h; if (gone) void h?.remove?.(); })
    .catch(() => {});
  return () => { gone = true; void handle?.remove?.(); };
}
