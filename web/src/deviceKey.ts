// This device's key, apart from the socket so a module that only reads it
// (a guest's own look, `companion/own.ts`) does not load the connection.
const DEVICE_KEY = "shengji.device";
/** Used when storage refuses: one key for this page's life. */
let memoryDevice: string | null = null;

/** 128 random bits as url-safe base64 without padding: 22 characters. */
function newDeviceKey(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** This device's opaque key, made on first use and kept in storage. The
 *  server uses it to tell two tabs on one device apart from two people. It
 *  identifies a browser, not a person: clearing site data makes a new one. */
export function deviceKey(): string {
  try {
    const saved = localStorage.getItem(DEVICE_KEY);
    if (saved && /^[A-Za-z0-9_-]{22}$/.test(saved)) return saved;
    const made = newDeviceKey();
    localStorage.setItem(DEVICE_KEY, made);
    return made;
  } catch {
    memoryDevice ??= newDeviceKey();
    return memoryDevice;
  }
}
