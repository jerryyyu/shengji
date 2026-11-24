// The app's two launch paths, the hosted page and the bundled offline page,
// are two origins with two localStorages. An explicit Language choice lives
// in the native store (Capacitor Preferences) too, and each path reads it
// before its first render; Follow system is stored there as "system". An
// empty native store (a build-10 install) is no choice at all: the origin's
// own choice stands and moves into it. A browser keeps the choice per origin.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type LocaleModule = typeof import("./locale");

const KEY = "shengji.language";
let native: Map<string, string>;
let calls: string[];
let pluginAvailable: boolean;
let slowGet: boolean;
const origins = new Map<string, Record<string, string>>();
let current = "";

function installBridge() {
  const store = {
    get: ({ key }: { key: string }) => {
      calls.push(`get ${key}`);
      if (slowGet) return new Promise(() => {});
      return Promise.resolve({ value: native.get(key) ?? null });
    },
    set: ({ key, value }: { key: string; value: string }) => {
      calls.push(`set ${key}=${value}`);
      native.set(key, value);
      return Promise.resolve();
    },
    remove: ({ key }: { key: string }) => {
      calls.push(`remove ${key}`);
      native.delete(key);
      return Promise.resolve();
    },
  };
  (window as unknown as { Capacitor?: unknown }).Capacitor = {
    isNativePlatform: () => true,
    isPluginAvailable: (name: string) => pluginAvailable && name === "Preferences",
    registerPlugin: (name: string) => (name === "Preferences" ? store : {}),
  };
}

function deviceLanguages(tags: string[]) {
  Object.defineProperty(navigator, "languages", { configurable: true, get: () => tags });
}

/** Leaves the current origin (keeping its storage) and opens `name` as a
 *  fresh page: its own localStorage, a freshly imported locale module. */
async function open(name: string): Promise<LocaleModule> {
  if (current) {
    const saved: Record<string, string> = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)!;
      saved[k] = localStorage.getItem(k)!;
    }
    origins.set(current, saved);
  }
  localStorage.clear();
  for (const [k, v] of Object.entries(origins.get(name) ?? {})) localStorage.setItem(k, v);
  current = name;
  vi.resetModules();
  return import("./locale");
}

beforeEach(() => {
  native = new Map();
  calls = [];
  pluginAvailable = true;
  slowGet = false;
  origins.clear();
  current = "";
  localStorage.clear();
  installBridge();
  deviceLanguages(["en-US"]);
});

afterEach(() => {
  delete (window as unknown as { Capacitor?: unknown }).Capacitor;
  delete (navigator as unknown as { languages?: unknown }).languages;
  localStorage.clear();
  document.documentElement.lang = "en";
});

describe("the app's language choice across its two origins", () => {
  it("hosted → offline: 中文 chosen on the hosted page draws the offline page in Chinese", async () => {
    const hosted = await open("https://shengji.fly.dev");
    await hosted.loadLanguage();
    expect(hosted.locale()).toBe("en");
    hosted.setLanguageChoice("zh-Hans");
    await hosted.languageSaved();
    expect(native.get(KEY)).toBe("zh-Hans");

    const offline = await open("capacitor://localhost");
    // this origin's own storage has nothing: without the native read it would draw English
    expect(offline.locale()).toBe("en");
    await offline.loadLanguage();
    expect(offline.locale()).toBe("zh-Hans");
    expect(offline.languageChoice()).toBe("zh-Hans");
    expect(document.documentElement.lang).toBe("zh-Hans");
    expect(localStorage.getItem(KEY)).toBe("zh-Hans");
  });

  it("offline → hosted: English chosen offline on a Chinese device wins over the hosted page's older 中文", async () => {
    deviceLanguages(["zh-Hans-CN"]);
    const hosted = await open("https://shengji.fly.dev");
    await hosted.loadLanguage();
    hosted.setLanguageChoice("zh-Hans");
    await hosted.languageSaved();

    const offline = await open("capacitor://localhost");
    await offline.loadLanguage();
    expect(offline.locale()).toBe("zh-Hans");
    offline.setLanguageChoice("en");
    await offline.languageSaved();
    expect(native.get(KEY)).toBe("en");

    const back = await open("https://shengji.fly.dev");
    expect(back.languageChoice()).toBe("zh-Hans");   // its stale local copy
    await back.loadLanguage();
    expect(back.languageChoice()).toBe("en");
    expect(back.locale()).toBe("en");
    expect(localStorage.getItem(KEY)).toBe("en");
  });

  it("Follow system on either path clears the choice for both", async () => {
    deviceLanguages(["zh-CN"]);
    const hosted = await open("https://shengji.fly.dev");
    await hosted.loadLanguage();
    hosted.setLanguageChoice("en");
    await hosted.languageSaved();
    expect(hosted.locale()).toBe("en");

    const offline = await open("capacitor://localhost");
    await offline.loadLanguage();
    expect(offline.locale()).toBe("en");
    offline.setLanguageChoice("system");
    await offline.languageSaved();
    expect(native.get(KEY)).toBe("system");
    expect(offline.locale()).toBe("zh-Hans");

    const back = await open("https://shengji.fly.dev");
    expect(back.languageChoice()).toBe("en");        // its stale local copy
    await back.loadLanguage();
    expect(back.languageChoice()).toBe("system");
    expect(back.locale()).toBe("zh-Hans");
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("a build-10 install: the hosted 中文 survives an empty native store and moves into it", async () => {
    await open("https://shengji.fly.dev");
    localStorage.setItem(KEY, "zh-Hans");          // chosen under build 10, per origin
    const hosted = await open("https://shengji.fly.dev");
    expect(native.has(KEY)).toBe(false);
    await hosted.loadLanguage();
    expect(hosted.languageChoice()).toBe("zh-Hans");
    expect(hosted.locale()).toBe("zh-Hans");
    expect(localStorage.getItem(KEY)).toBe("zh-Hans");
    await hosted.languageSaved();
    expect(native.get(KEY)).toBe("zh-Hans");

    const offline = await open("capacitor://localhost");
    await offline.loadLanguage();
    expect(offline.locale()).toBe("zh-Hans");
  });

  it("a build-10 install that opens offline first still keeps the hosted 中文", async () => {
    await open("https://shengji.fly.dev");
    localStorage.setItem(KEY, "zh-Hans");          // chosen under build 10, per origin
    const offline = await open("capacitor://localhost");
    await offline.loadLanguage();
    await offline.languageSaved();
    expect(offline.locale()).toBe("en");          // nothing chosen here, nothing stored natively
    expect(native.has(KEY)).toBe(false);

    const hosted = await open("https://shengji.fly.dev");
    await hosted.loadLanguage();
    expect(hosted.locale()).toBe("zh-Hans");
    await hosted.languageSaved();
    expect(native.get(KEY)).toBe("zh-Hans");

    const again = await open("capacitor://localhost");
    await again.loadLanguage();
    expect(again.locale()).toBe("zh-Hans");
  });

  it("an explicit Follow system after the migration clears the 中文 on both origins", async () => {
    deviceLanguages(["en-US"]);
    await open("https://shengji.fly.dev");
    localStorage.setItem(KEY, "zh-Hans");
    const hosted = await open("https://shengji.fly.dev");
    await hosted.loadLanguage();
    await hosted.languageSaved();
    expect(native.get(KEY)).toBe("zh-Hans");
    hosted.setLanguageChoice("system");
    await hosted.languageSaved();
    expect(native.get(KEY)).toBe("system");
    expect(localStorage.getItem(KEY)).toBeNull();

    const offline = await open("capacitor://localhost");
    await offline.loadLanguage();
    expect(offline.languageChoice()).toBe("system");
    expect(offline.locale()).toBe("en");
    const back = await open("https://shengji.fly.dev");
    await back.loadLanguage();
    expect(back.languageChoice()).toBe("system");
    expect(back.locale()).toBe("en");
  });

  it("a shell built without the plugin keeps the choice per origin", async () => {
    pluginAvailable = false;
    const hosted = await open("https://shengji.fly.dev");
    expect(hosted.loadLanguage()).toBeNull();
    hosted.setLanguageChoice("zh-Hans");
    expect(calls).toEqual([]);
    expect(localStorage.getItem(KEY)).toBe("zh-Hans");
  });

  it("a native store that does not answer in time leaves the origin's own choice", async () => {
    await open("https://shengji.fly.dev");
    localStorage.setItem(KEY, "zh-Hans");
    slowGet = true;
    const again = await open("https://shengji.fly.dev");
    expect(again.languageChoice()).toBe("zh-Hans");
    await again.loadLanguage(10);
    expect(again.locale()).toBe("zh-Hans");
  });
});

describe("a browser", () => {
  it("has no native store: renders at once and keeps the choice per origin", async () => {
    delete (window as unknown as { Capacitor?: unknown }).Capacitor;
    const page = await open("https://shengji.fly.dev");
    expect(page.loadLanguage()).toBeNull();
    page.setLanguageChoice("zh-Hans");
    expect(localStorage.getItem(KEY)).toBe("zh-Hans");
    const other = await open("https://playshengji.com");
    expect(other.loadLanguage()).toBeNull();
    expect(other.locale()).toBe("en");
    expect(calls).toEqual([]);
  });
});
