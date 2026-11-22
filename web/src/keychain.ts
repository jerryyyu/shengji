// The device secret in the iOS Keychain (the shell's ShengjiKeychain plugin,
// KeychainPlugin.swift). The Keychain keeps it when the app is deleted, so a
// reinstall reads the same value back; it is never synced to iCloud.
//
// Like src/native.ts, nothing here imports a Capacitor package: the plugin is
// reached by name through the bridge the shell injects. In a browser, or in an
// app build that predates the plugin, there is no Keychain: `get` resolves
// null and `set` and `remove` do nothing. A failing Keychain call in the app
// rejects with the OSStatus as the error's `code`.

import { isNative } from "./native";

export const KEYCHAIN_PLUGIN = "ShengjiKeychain";

type Method = (opts?: Record<string, unknown>) => Promise<unknown>;

interface Bridge {
  isPluginAvailable?: (name: string) => boolean;
  registerPlugin?: (name: string) => Record<string, Method | undefined>;
  Plugins?: Record<string, Record<string, Method | undefined> | undefined>;
}

function method(name: "get" | "set" | "remove"): Method | null {
  if (!isNative()) return null;
  const cap = (window as unknown as { Capacitor?: Bridge }).Capacitor;
  if (!cap) return null;
  try {
    if (typeof cap.isPluginAvailable === "function" && !cap.isPluginAvailable(KEYCHAIN_PLUGIN)) return null;
    const proxy = cap.registerPlugin?.(KEYCHAIN_PLUGIN) ?? cap.Plugins?.[KEYCHAIN_PLUGIN];
    const fn = proxy?.[name];
    return typeof fn === "function" ? fn : null;
  } catch {
    return null;
  }
}

/** True only in an app build whose shell carries the plugin. */
export function keychainAvailable(): boolean {
  return method("get") !== null;
}

/** The stored secret, or null when there is none or no Keychain. */
export async function keychainGet(): Promise<string | null> {
  const fn = method("get");
  if (!fn) return null;
  const r = (await fn()) as { value?: unknown } | undefined;
  return typeof r?.value === "string" ? r.value : null;
}

/** Stores the secret, replacing any earlier one; no-op without a Keychain. */
export async function keychainSet(value: string): Promise<void> {
  if (!value) throw new Error("keychainSet needs a non-empty value");
  const fn = method("set");
  if (!fn) return;
  await fn({ value });
}

/** Deletes the secret; no-op without a Keychain. */
export async function keychainRemove(): Promise<void> {
  const fn = method("remove");
  if (!fn) return;
  await fn();
}
