import { describe, expect, it } from "vitest";

import { decideIntent, intentToJoin } from "./intent";

describe("connection intent precedence", () => {
  it("prefers an invite over the saved room", () => {
    const i = decideIntent({
      invite: { room: "aaaa" },
      savedRoom: "ZZZZ", savedName: "jerry", savedToken: "tok",
    });
    expect(i).toEqual({ kind: "invite", room: "AAAA", name: undefined });
    // No name on the link => do NOT auto-join; the lobby focuses the name field.
    expect(intentToJoin(i)).toBeNull();
  });

  it("auto-joins an invite that carries a name", () => {
    const i = decideIntent({ invite: { room: "bbbb", name: "James" } });
    expect(intentToJoin(i)).toEqual({
      type: "join_room", room: "BBBB", name: "James",
    });
  });

  it("prefers an explicit pending action over the saved room", () => {
    const i = decideIntent({
      pending: { room: "cccc", name: "sk", seat: 2 },
      savedRoom: "ZZZZ", savedName: "jerry",
    });
    expect(i.kind).toBe("pending");
    expect(intentToJoin(i)).toEqual({
      type: "join_room", room: "CCCC", name: "sk", seat: 2,
    });
  });

  it("falls back to the saved room, carrying the resume token", () => {
    const i = decideIntent({
      savedRoom: "dddd", savedName: "jerry", savedToken: "tok-1",
    });
    expect(intentToJoin(i)).toEqual({
      type: "join_room", room: "DDDD", name: "jerry", token: "tok-1",
    });
  });

  it("sends nothing when there is no room to be in", () => {
    expect(decideIntent({}).kind).toBe("none");
    expect(intentToJoin(decideIntent({}))).toBeNull();
    // A saved room with no name cannot join: the server needs both.
    expect(decideIntent({ savedRoom: "EEEE" }).kind).toBe("none");
  });

  it("ignores a malformed invite code", () => {
    const i = decideIntent({ invite: { room: "AB" }, savedRoom: "ZZZZ",
                             savedName: "jerry" });
    expect(i.kind).toBe("resume");   // falls through, does not join "AB"
  });
});
