// The code lookup's own state, without a screen: an App test sees App's
// error toast in the Play box too, which would hide a lookup that drops a
// refusal.
import { beforeEach, describe, expect, it, vi } from "vitest";

const { sent, link } = vi.hoisted(() => ({
  sent: [] as Record<string, unknown>[],
  link: { msg: new Set<(m: unknown) => void>(), status: new Set<(s: string) => void>() },
}));
vi.mock("./ws", () => ({
  conn: {
    send: (m: Record<string, unknown>) => { sent.push(m); return true; },
    subscribe: (fn: (m: unknown) => void) => { link.msg.add(fn); return () => link.msg.delete(fn); },
    subscribeStatus: (fn: (s: string) => void) => { link.status.add(fn); return () => link.status.delete(fn); },
  },
}));

import { codes } from "./codeJoin";
import { NO_CODE } from "./codes";
import { queue } from "./queue/store";

const say = (m: unknown) => { for (const fn of [...link.msg]) fn(m); };
const status = (s: string) => { for (const fn of [...link.status]) fn(s); };
const LIMITED = { type: "error", code: "rate_limited", lookup: "FG3K", message: "Too many requests; wait a minute." };

beforeEach(() => {
  sent.length = 0;
  codes.reset();
  queue.reset();
  window.history.replaceState(null, "", "/");
});

describe("a refused lookup", () => {
  it("from the Play box is the Play box's error", () => {
    codes.lookup("wxyz", "play");
    say(LIMITED);
    expect(codes.view).toMatchObject({ pending: null, playError: LIMITED.message });
  });

  it("from a ?code= link is the Play box's error", () => {
    window.history.replaceState(null, "", "/?code=WXYZ");
    status("open");
    expect(sent).toEqual([{ type: "code_lookup", code: "WXYZ" }]);
    say(LIMITED);
    expect(codes.view).toMatchObject({ pending: null, playError: LIMITED.message });
  });

  it("a queue or pair message's own rate_limited leaves the lookup waiting", () => {
    codes.lookup("WXYZ", "play");
    say({ type: "error", code: "rate_limited", message: "Too many requests; wait a minute." });
    expect(codes.view.pending).toEqual({ code: "WXYZ", from: "play" });
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    expect(codes.view.room).toMatchObject({ code: "WXYZ", from: "play" });
  });

  it("a queue or pair message's own rate_limited is not taken for a cancelled lookup's reply", () => {
    codes.lookup("WXYZ", "play");
    codes.cancel();
    say({ type: "error", code: "rate_limited", message: "Too many requests; wait a minute." });
    codes.lookup("WXYZ", "play");
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    expect(codes.view.pending).toEqual({ code: "WXYZ", from: "play" });
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    expect(codes.view.room).toMatchObject({ code: "WXYZ", from: "play" });
  });

  it("an unrelated error leaves the lookup waiting", () => {
    codes.lookup("WXYZ", "play");
    say({ type: "error", code: "room_full", message: "Room is full." });
    expect(codes.view.pending).toEqual({ code: "WXYZ", from: "play" });
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    expect(codes.view.room).toMatchObject({ code: "WXYZ", from: "play" });
  });
});

describe("a ?code= link across reconnects", () => {
  it("is asked once more when its lookup died with the socket", () => {
    window.history.replaceState(null, "", "/?code=WXYZ");
    status("open");
    status("closed");
    status("open");
    expect(sent).toEqual([{ type: "code_lookup", code: "WXYZ" }, { type: "code_lookup", code: "WXYZ" }]);
    expect(codes.view.pending).toEqual({ code: "WXYZ", from: "link" });
  });

  it("is not asked again once answered", () => {
    window.history.replaceState(null, "", "/?code=WXYZ");
    status("open");
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    status("closed");
    status("open");
    expect(sent).toHaveLength(1);
  });
});

describe("a cancelled lookup", () => {
  it("ignores its late answer: no join, no room, no error", () => {
    codes.lookup("FG3K", "play");
    codes.cancel();
    expect(codes.view.pending).toBeNull();
    say({ type: "code_kind", code: "FG3K", kind: "party" });
    say({ type: "code_kind", code: "FG3K", kind: "room" });
    expect(sent).toEqual([{ type: "code_lookup", code: "FG3K" }]);
    expect(codes.view.room).toBeNull();
    expect(codes.view.playError).toBeNull();
  });

  it("drops only its own answer: a fresh lookup after it is answered", () => {
    codes.lookup("FG3K", "play");
    codes.cancel();
    codes.lookup("WXYZ", "play");
    say({ type: "code_kind", code: "FG3K", kind: "party" });
    expect(codes.view.pending).toEqual({ code: "WXYZ", from: "play" });
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    expect(codes.view.room).toMatchObject({ code: "WXYZ", from: "play" });
  });

  it("the same code asked again after a cancel takes the second answer", () => {
    codes.lookup("WXYZ", "play");
    codes.cancel();
    codes.lookup("WXYZ", "play");
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    expect(codes.view.pending).toEqual({ code: "WXYZ", from: "play" });
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    expect(codes.view.room).toMatchObject({ code: "WXYZ", from: "play" });
  });

  it("a refused cancelled lookup is dropped too", () => {
    codes.lookup("FG3K", "play");
    codes.cancel();
    say(LIMITED);
    expect(codes.view.playError).toBeNull();
    expect(codes.view.playError).toBeNull();
  });
});

describe("an older ?party= link", () => {
  it("is an alias of ?code=: the code is looked up and the address reads ?code=", () => {
    window.history.replaceState(null, "", "/?party=FG3K");
    status("open");
    expect(sent).toEqual([{ type: "code_lookup", code: "FG3K" }]);
    expect(window.location.search).toBe("?code=FG3K");
    say({ type: "code_kind", code: "FG3K", kind: "table" });
    expect(codes.view.room).toMatchObject({ code: "FG3K", from: "link", kind: "table" });
  });

  it("names no table when its code is an old pair's or nothing's, and joins no pair", () => {
    for (const kind of ["party", "none"]) {
      codes.reset();
      sent.length = 0;
      window.history.replaceState(null, "", "/?party=FG3K");
      status("open");
      say({ type: "code_kind", code: "FG3K", kind });
      expect(codes.view.playError).toBe(NO_CODE);
      expect(NO_CODE).toBe("No table has that code.");
      expect(sent.some((m) => m.type === "party_join")).toBe(false);
    }
  });
});

describe("one link kind: an older ?room= link", () => {
  it("is an alias of ?code=: looked up as any code, its ?name= dropped", () => {
    window.history.replaceState(null, "", "/?room=wxyz&name=Ann");
    status("open");
    expect(sent).toEqual([{ type: "code_lookup", code: "WXYZ" }]);
    expect(window.location.search).toBe("?code=wxyz");
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    expect(codes.view.room).toMatchObject({ code: "WXYZ", from: "link", kind: "room" });
  });

  it("leaves a ?code= link as it is when it has one too", () => {
    window.history.replaceState(null, "", "/?code=ABCD&room=WXYZ");
    status("open");
    expect(sent).toEqual([{ type: "code_lookup", code: "ABCD" }]);
    expect(window.location.search).toBe("?code=ABCD");
  });
});
