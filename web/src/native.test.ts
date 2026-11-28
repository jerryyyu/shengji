/// <reference types="node" />
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { TAB_TOP_EVENT } from "./home/session";
import {
  GAME_WON_FOLLOW, KEYBOARD_OPEN_CLASS, STATUS_TAP_EVENT, haptic, hapticCall, hapticsEnabled, hideSplash, isNative, deviceIdiom,
  PHONE_WINDOW_SHORT_SIDE, lockFor, orientationLockFor, resetNativeForTests, setHapticsEnabled, subscribeHaptics, setBackGesture, setGameMode, startShell,
} from "./native";

type Calls = [string, string, unknown][];

function fakeShell(idiom: "phone" | "pad"): Calls {
  const calls: Calls = [];
  const plugin = (name: string) => new Proxy({}, {
    get: (_t, method: string) => (opts?: unknown) => {
      calls.push([name, method, opts]);
      return Promise.resolve(name === "ShengjiShell" && method === "idiom" ? { idiom } : undefined);
    },
  });
  (window as unknown as { Capacitor: unknown }).Capacitor = {
    isNativePlatform: () => true,
    registerPlugin: plugin,
  };
  return calls;
}

const jsdomSize = [window.innerWidth, window.innerHeight] as const;

/** Sizes the window as a WebView of this many points, telling listeners. */
function sizeWindow(width: number, height: number): void {
  Object.defineProperty(window, "innerWidth", { value: width, configurable: true });
  Object.defineProperty(window, "innerHeight", { value: height, configurable: true });
  window.dispatchEvent(new Event("resize"));
}

afterEach(() => {
  delete (window as unknown as { Capacitor?: unknown }).Capacitor;
  resetNativeForTests();
  sizeWindow(...jsdomSize);
});

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("native bridge", () => {
  it("is a no-op in a browser", async () => {
    expect(isNative()).toBe(false);
    expect(await deviceIdiom()).toBe(null);
    await lockFor("game");
    haptic("turn");
    hideSplash();   // nothing to call, nothing thrown
    await setGameMode(true);
    startShell();
    window.dispatchEvent(new Event("keyboardWillShow"));
    expect(document.body.classList.contains(KEYBOARD_OPEN_CLASS)).toBe(false);
    let tops = 0;
    const onTop = () => { tops += 1; };
    window.addEventListener(TAB_TOP_EVENT, onTop);
    window.dispatchEvent(new Event(STATUS_TAP_EVENT));
    window.removeEventListener(TAB_TOP_EVENT, onTop);
    expect(tops).toBe(0);
  });

  it("turns game mode on and off through the shell and SystemBars, only when it changes", async () => {
    const calls = fakeShell("pad");
    await setGameMode(true);
    await setGameMode(true);
    await setGameMode(false);
    expect(calls).toEqual([
      ["ShengjiShell", "setGameMode", { on: true }],
      ["SystemBars", "hide", { bar: "NavigationBar" }],
      ["ShengjiShell", "setGameMode", { on: false }],
      ["SystemBars", "show", { bar: "NavigationBar" }],
    ]);
  });

  it("hides the keyboard accessory bar once at startup", () => {
    const calls = fakeShell("phone");
    startShell();
    startShell();
    expect(calls).toEqual([["Keyboard", "setAccessoryBarVisible", { isVisible: false }]]);
  });

  it("hides the tab bar while the keyboard is up", () => {
    // jsdom's URL is not node's, so the path is built from the directory
    const css = readFileSync(`${import.meta.dirname}/index.css`, "utf8");
    // the page follows the shrunken WebView, not 100dvh, while the keyboard is up
    expect(css).toMatch(/body\.keyboard-open \.app \{ height: 100%; \}/);
    const rule = css.match(/body\.keyboard-open \.tabbar \{[^}]*\}/);
    expect(rule).not.toBeNull();
    const style = document.createElement("style");
    style.textContent = rule![0];
    document.head.appendChild(style);
    const tabbar = document.createElement("nav");
    tabbar.className = "tabbar";
    document.body.appendChild(tabbar);
    try {
      fakeShell("phone");
      startShell();
      expect(getComputedStyle(tabbar).display).not.toBe("none");
      window.dispatchEvent(new Event("keyboardWillShow"));
      expect(document.body.classList.contains(KEYBOARD_OPEN_CLASS)).toBe(true);
      expect(getComputedStyle(tabbar).display).toBe("none");
      window.dispatchEvent(new Event("keyboardWillHide"));
      expect(document.body.classList.contains(KEYBOARD_OPEN_CLASS)).toBe(false);
      expect(getComputedStyle(tabbar).display).not.toBe("none");
    } finally {
      tabbar.remove();
      style.remove();
    }
  });

  it("brings the focused field into view when the keyboard shrinks the page", () => {
    const input = document.createElement("input");
    document.body.appendChild(input);
    const scrolled: unknown[] = [];
    input.scrollIntoView = (opts?: unknown) => { scrolled.push(opts); };
    try {
      fakeShell("phone");
      startShell();
      input.focus();
      window.dispatchEvent(new Event("resize"));        // no keyboard: left alone
      expect(scrolled).toEqual([]);
      window.dispatchEvent(new Event("keyboardWillShow"));
      window.dispatchEvent(new Event("resize"));
      expect(scrolled).toEqual([{ block: "center" }]);
    } finally {
      input.remove();
    }
  });

  it("a tap on plain page puts the keyboard away; a tap on a control or field keeps it", () => {
    const screen = document.createElement("div");
    screen.innerHTML = '<p class="plain">text</p><input class="code"><input class="name"><button class="join">Join</button>';
    document.body.appendChild(screen);
    const q = (s: string) => screen.querySelector<HTMLElement>(s)!;
    const tap = (el: Element) => el.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    try {
      fakeShell("phone");
      startShell();
      q(".code").focus();
      tap(q(".join"));
      expect(document.activeElement).toBe(q(".code"));
      tap(q(".name"));
      expect(document.activeElement).toBe(q(".code"));   // focus moves on the field's own click
      tap(q(".plain"));
      expect(document.activeElement).toBe(document.body);
      q(".code").focus();
      tap(document.body);
      expect(document.activeElement).toBe(document.body);
    } finally {
      screen.remove();
    }
  });

  it("the web page leaves focus alone on a tap", () => {
    const input = document.createElement("input");
    document.body.appendChild(input);
    try {
      startShell();
      input.focus();
      document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }));
      expect(document.activeElement).toBe(input);
    } finally {
      input.remove();
    }
  });

  it("scrolls a scrolled screen without tab scroll memory (the Play lobby) to the top", () => {
    const screen = document.createElement("div");
    screen.className = "screen";
    document.body.appendChild(screen);
    const calls: unknown[] = [];
    screen.scrollTo = ((opts: unknown) => { calls.push(opts); }) as typeof screen.scrollTo;
    try {
      fakeShell("phone");
      startShell();
      window.dispatchEvent(new Event(STATUS_TAP_EVENT));   // at the top already
      expect(calls).toEqual([]);
      Object.defineProperty(screen, "scrollTop", { value: 67, configurable: true });
      window.dispatchEvent(new Event(STATUS_TAP_EVENT));
      expect(calls).toEqual([{ top: 0, behavior: "smooth" }]);
    } finally {
      screen.remove();
    }
  });

  it("scrolls the active tab to the top on a status-bar tap", () => {
    fakeShell("phone");
    startShell();
    let tops = 0;
    const onTop = () => { tops += 1; };
    window.addEventListener(TAB_TOP_EVENT, onTop);
    try {
      window.dispatchEvent(new Event(STATUS_TAP_EVENT));
      expect(tops).toBe(1);
      resetNativeForTests();      // listeners come off with the shell
      window.dispatchEvent(new Event(STATUS_TAP_EVENT));
      expect(tops).toBe(1);
    } finally {
      window.removeEventListener(TAB_TOP_EVENT, onTop);
    }
  });

  it("locks a phone-sized window: the table to both landscapes, the lobby to portrait", async () => {
    sizeWindow(402, 874);
    const calls = fakeShell("phone");
    await lockFor("game");
    await lockFor("game");          // unchanged screen: no second call
    await lockFor("lobby");
    expect(calls).toEqual([
      ["ShengjiShell", "lockOrientation", { orientation: "landscape" }],
      ["ScreenOrientation", "lock", { orientation: "portrait" }],
    ]);
  });

  it("decides the lock by the window's shorter side, whatever the idiom or turn", () => {
    const cases: [number, number, "lobby" | "game", string | null][] = [
      [402, 874, "lobby", "portrait"],     // phone, portrait
      [874, 402, "game", "landscape"],     // phone, turned
      [599, 900, "game", "landscape"],     // just under the line
      [600, 900, "game", "free"],          // on the line
      [744, 1133, "lobby", "free"],        // iPad mini, full screen
      [1133, 744, "game", "free"],
      [800, 760, "game", "free"],          // a near-square unfolded foldable
      [320, 1133, "lobby", "portrait"],    // a narrow iPad window
      [0, 0, "game", null],                // not laid out yet
    ];
    for (const [w, h, screen, want] of cases) {
      expect(orientationLockFor(screen, w, h), `${w}x${h} ${screen}`).toBe(want);
    }
    expect(PHONE_WINDOW_SHORT_SIDE).toBe(600);
  });

  for (const idiom of ["phone", "pad"] as const) {
    it(`never locks a large window, reporting ${idiom}`, async () => {
      sizeWindow(744, 1133);
      const calls = fakeShell(idiom);
      await lockFor("game");
      await lockFor("lobby");
      expect(calls).toEqual([]);
    });
  }

  it("releases the lock on an unfold and takes it again on a fold, mid-game", async () => {
    sizeWindow(874, 402);           // folded, at the table
    const calls = fakeShell("phone");
    await lockFor("game");
    sizeWindow(402, 874);           // the same window turned: still phone-sized
    sizeWindow(820, 760);           // unfolded
    await flush();
    sizeWindow(760, 820);           // turned while unfolded: still free
    await flush();
    sizeWindow(874, 402);           // folded again
    await flush();
    expect(calls).toEqual([
      ["ShengjiShell", "lockOrientation", { orientation: "landscape" }],
      ["ShengjiShell", "lockOrientation", { orientation: "any" }],
      ["ShengjiShell", "lockOrientation", { orientation: "landscape" }],
    ]);
  });

  it("follows the screen after an unfold: the lobby stays free until the window is phone-sized", async () => {
    sizeWindow(820, 760);
    const calls = fakeShell("phone");
    await lockFor("game");
    await lockFor("lobby");
    sizeWindow(402, 874);
    await flush();
    expect(calls).toEqual([["ScreenOrientation", "lock", { orientation: "portrait" }]]);
  });

  it("keeps the lock while the keyboard shrinks the WebView", async () => {
    sizeWindow(1133, 744);
    const calls = fakeShell("pad");
    await lockFor("lobby");
    document.body.classList.add(KEYBOARD_OPEN_CLASS);
    sizeWindow(1133, 400);          // the space above the keyboard
    await flush();
    document.body.classList.remove(KEYBOARD_OPEN_CLASS);
    sizeWindow(1133, 744);
    await flush();
    expect(calls).toEqual([]);
  });

  it("stops following the window once the shell is reset", async () => {
    sizeWindow(402, 874);
    const calls = fakeShell("phone");
    await lockFor("lobby");
    resetNativeForTests();
    sizeWindow(820, 760);
    await flush();
    expect(calls).toEqual([["ScreenOrientation", "lock", { orientation: "portrait" }]]);
  });

  it("sets the edge swipe back only when it changes, on any device", async () => {
    await setBackGesture(false);    // a browser: nothing to call
    const calls = fakeShell("pad");
    await setBackGesture(true);
    await setBackGesture(true);
    await setBackGesture(false);
    expect(calls).toEqual([
      ["ShengjiShell", "setBackGesture", { enabled: true }],
      ["ShengjiShell", "setBackGesture", { enabled: false }],
    ]);
  });

  it("maps each table event to a UIKit feedback style", async () => {
    expect(hapticCall("turn")).toEqual({ method: "impact", opts: { style: "LIGHT" } });
    expect(hapticCall("clock")).toEqual({ method: "impact", opts: { style: "LIGHT" } });
    expect(hapticCall("declare")).toEqual({ method: "impact", opts: { style: "MEDIUM" } });
    expect(hapticCall("won")).toEqual({ method: "notification", opts: { type: "SUCCESS" } });
    expect(hapticCall("error")).toEqual({ method: "notification", opts: { type: "ERROR" } });
    expect(hapticCall("sheet")).toEqual({ method: "impact", opts: { style: "LIGHT" } });
    const calls = fakeShell("phone");
    haptic("select");
    await flush();
    haptic("select");
    haptic("won");
    await flush();
    expect(calls.map(([n, m]) => `${n}.${m}`)).toEqual([
      "Haptics.selectionStart", "Haptics.selectionChanged", "Haptics.selectionChanged", "Haptics.notification",
    ]);
  });

  it("plays a won game as its own pattern: success, then a medium impact; a won round is the success alone", async () => {
    vi.useFakeTimers();
    try {
      const calls = fakeShell("phone");
      haptic("won");
      vi.advanceTimersByTime(1000);
      await Promise.resolve();
      expect(calls).toEqual([["Haptics", "notification", { type: "SUCCESS" }]]);
      calls.length = 0;
      haptic("game");
      expect(calls).toEqual([["Haptics", "notification", { type: "SUCCESS" }]]);
      vi.advanceTimersByTime(GAME_WON_FOLLOW.afterMs);
      expect(calls).toEqual([["Haptics", "notification", { type: "SUCCESS" }], ["Haptics", "impact", { style: "MEDIUM" }]]);
      // the Haptics setting silences both beats
      calls.length = 0;
      setHapticsEnabled(false);
      haptic("game");
      vi.advanceTimersByTime(1000);
      expect(calls).toEqual([]);
      setHapticsEnabled(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("plays no haptic while the Haptics setting is off, and remembers the setting", async () => {
    localStorage.removeItem("shengji.haptics");
    resetNativeForTests();
    expect(hapticsEnabled()).toBe(true);
    const seen: boolean[] = [];
    const stop = subscribeHaptics((on) => seen.push(on));
    const calls = fakeShell("phone");
    setHapticsEnabled(false);
    haptic("won");
    haptic("select");
    await flush();
    expect(calls).toEqual([]);
    expect(localStorage.getItem("shengji.haptics")).toBe("0");
    resetNativeForTests();
    expect(hapticsEnabled()).toBe(false);
    setHapticsEnabled(true);
    haptic("won");
    await flush();
    expect(calls.map(([n, m]) => `${n}.${m}`)).toEqual(["Haptics.notification"]);
    stop();
    expect(seen).toEqual([false, true]);
    localStorage.removeItem("shengji.haptics");
  });

  it("hides the splash once", () => {
    const calls = fakeShell("phone");
    hideSplash();
    hideSplash();
    expect(calls).toEqual([["SplashScreen", "hide", { fadeOutDuration: 200 }]]);
  });

  it("swallows a plugin the shell does not have", async () => {
    (window as unknown as { Capacitor: unknown }).Capacitor = {
      isNativePlatform: () => true,
      registerPlugin: () => ({ idiom: () => Promise.reject(new Error("not implemented")) }),
    };
    expect(await deviceIdiom()).toBe(null);
  });
});
