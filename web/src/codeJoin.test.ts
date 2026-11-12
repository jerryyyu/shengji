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
import { queue } from "./queue/store";

const say = (m: unknown) => { for (const fn of [...link.msg]) fn(m); };
const status = (s: string) => { for (const fn of [...link.status]) fn(s); };
const LIMITED = { type: "error", code: "rate_limited", message: "Too many requests; wait a minute." };

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

  it("from the pair sheet is the sheet's error, not the Play box's", () => {
    queue.openSheet("party");
    codes.lookup("WXYZ", "pair");
    say(LIMITED);
    expect(queue.view.partyError).toBe(LIMITED.message);
    expect(codes.view.playError).toBeNull();
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
    queue.openSheet("party");
    codes.lookup("FG3K", "pair");
    codes.cancel();
    expect(codes.view.pending).toBeNull();
    say({ type: "code_kind", code: "FG3K", kind: "party" });
    say({ type: "code_kind", code: "FG3K", kind: "room" });
    expect(sent).toEqual([{ type: "code_lookup", code: "FG3K" }]);
    expect(codes.view.room).toBeNull();
    expect(queue.view.partyError).toBeNull();
  });

  it("is what closing the pair sheet does to a pair-sheet lookup", () => {
    queue.openSheet("party");
    codes.lookup("FG3K", "pair");
    queue.closeSheet();
    expect(codes.view.pending).toBeNull();
    say({ type: "code_kind", code: "FG3K", kind: "room" });
    expect(codes.view.room).toBeNull();
  });

  it("leaves a Play-box lookup alone when the pair sheet closes", () => {
    queue.openSheet("party");
    codes.lookup("WXYZ", "play");
    queue.closeSheet();
    expect(codes.view.pending).toEqual({ code: "WXYZ", from: "play" });
  });

  it("drops only its own answer: a fresh lookup after it is answered", () => {
    queue.openSheet("party");
    codes.lookup("FG3K", "pair");
    codes.cancel();
    codes.lookup("WXYZ", "play");
    say({ type: "code_kind", code: "FG3K", kind: "party" });
    expect(codes.view.pending).toEqual({ code: "WXYZ", from: "play" });
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    expect(codes.view.room).toMatchObject({ code: "WXYZ", from: "play" });
  });

  it("the same code asked again after a cancel takes the second answer", () => {
    queue.openSheet("party");
    codes.lookup("WXYZ", "pair");
    codes.cancel();
    codes.lookup("WXYZ", "play");
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    expect(codes.view.pending).toEqual({ code: "WXYZ", from: "play" });
    say({ type: "code_kind", code: "WXYZ", kind: "room" });
    expect(codes.view.room).toMatchObject({ code: "WXYZ", from: "play" });
  });

  it("a refused cancelled lookup is dropped too", () => {
    queue.openSheet("party");
    codes.lookup("FG3K", "pair");
    codes.cancel();
    say(LIMITED);
    expect(queue.view.partyError).toBeNull();
    expect(codes.view.playError).toBeNull();
  });
});
