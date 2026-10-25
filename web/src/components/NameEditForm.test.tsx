import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthUser } from "../auth";

const { updated, updateDisplayName } = vi.hoisted(() => ({
  updated: vi.fn(),
  updateDisplayName: vi.fn(),
}));
vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return { ...real, updateDisplayName, auth: { updated } };
});

import NameEditForm from "./NameEditForm";
import { NameRejected } from "../auth";

const JERRY: AuthUser = { name: "Jerry Yu", email: "jerry@example.com", picture: null,
                          display_name: null, name_shown: "Jerry" };

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const onDone = vi.fn();

function render(user: AuthUser = JERRY) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<NameEditForm user={user} onDone={onDone} />));
}
const input = () => host.querySelector<HTMLInputElement>(".name-edit-input")!;
const error = () => host.querySelector(".name-edit-error")?.textContent ?? null;
function type(value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  act(() => {
    setter.call(input(), value);
    input().dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function submit() {
  await act(async () => {
    host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

beforeEach(() => { updated.mockClear(); updateDisplayName.mockReset(); onDone.mockClear(); });
afterEach(() => { act(() => root.unmount()); host.remove(); });

describe("the display-name form", () => {
  it("starts from the current name, caps the input at 20, and Cancel closes without a request", () => {
    render({ ...JERRY, display_name: "Captain", name_shown: "Captain" });
    expect(input().value).toBe("Captain");
    expect(input().maxLength).toBe(20);
    act(() => host.querySelector<HTMLButtonElement>(".name-edit-cancel")!.click());
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(updateDisplayName).not.toHaveBeenCalled();
  });

  it("explains each refusal before any request", async () => {
    render();
    for (const [value, fragment] of [
      ["", "Enter a name"],
      ["   ", "Enter a name"],
      ["x".repeat(25), "20 characters"],
      ["a\tb", "control characters"],      // an <input> drops newlines itself; a tab reaches the rule
      ["Bot 2", "reserved"],
      ["system", "reserved"],
    ] as const) {
      type(value);
      await submit();
      expect(error(), value).toContain(fragment);
    }
    expect(updateDisplayName).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
    type("Fine");                                 // typing clears the message
    expect(error()).toBeNull();
  });

  it("saves a valid name: PATCH, store update, close", async () => {
    const next = { ...JERRY, display_name: "Jerry Yu", name_shown: "Jerry Yu" };
    updateDisplayName.mockResolvedValue(next);
    render();
    type("  Jerry   Yu ");
    await submit();
    expect(updateDisplayName).toHaveBeenCalledWith("Jerry Yu");   // collapsed before it leaves
    expect(updated).toHaveBeenCalledWith(next);
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("an unchanged name just closes", async () => {
    render();
    await submit();
    expect(updateDisplayName).not.toHaveBeenCalled();
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("shows the server's refusal and stays open", async () => {
    updateDisplayName.mockRejectedValue(new NameRejected("not_allowed"));
    render();
    type("Something");
    await submit();
    expect(error()).toContain("not allowed");
    expect(onDone).not.toHaveBeenCalled();
    expect(updated).not.toHaveBeenCalled();
  });

  it("Escape in the field closes", () => {
    render();
    act(() => { input().dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});
