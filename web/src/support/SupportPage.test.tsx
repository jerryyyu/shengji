import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SupportPage from "./SupportPage";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const fetchMock = vi.fn();

function render() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<SupportPage />));
}
const q = <T extends Element>(sel: string) => host.querySelector<T>(sel)!;
function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")!.set!;
  act(() => {
    setter.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const message = () => q<HTMLTextAreaElement>("textarea");
const email = () => q<HTMLInputElement>('input[type="email"]');
const send = () => q<HTMLButtonElement>('button[type="submit"]');
async function submit() {
  await act(async () => {
    q("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("the support form", () => {
  it("labels every field, marks email optional, and hides the honeypot", () => {
    render();
    const labels = [...host.querySelectorAll(".field-label")].map((l) => l.textContent);
    expect(labels).toEqual(["Topic", "Message", "Email (optional)"]);
    expect(host.textContent).toContain("Only if you want a reply.");
    const options = [...host.querySelectorAll("option")].map((o) => o.textContent);
    expect(options).toEqual(["Bug", "Feedback", "Account", "Other"]);
    const trap = q<HTMLInputElement>('input[name="website"]');
    expect(trap.tabIndex).toBe(-1);
    expect(trap.closest(".support-trap")!.getAttribute("aria-hidden")).toBe("true");
    expect(host.textContent).not.toMatch(/@/);
  });

  it("waits for ten characters and a well-formed email before it can send", () => {
    render();
    expect(send().disabled).toBe(true);
    type(message(), "too short");
    expect(send().disabled).toBe(true);
    type(message(), "The table froze after I buried.");
    expect(send().disabled).toBe(false);
    type(email(), "not-an-email");
    expect(send().disabled).toBe(true);
    expect(email().getAttribute("aria-invalid")).toBe("true");
    type(email(), "me@example.com");
    expect(send().disabled).toBe(false);
  });

  it("posts the message with the version and shows the thanks state", async () => {
    fetchMock.mockResolvedValue({ status: 200, json: async () => ({ ok: true }) });
    render();
    act(() => {
      const select = q<HTMLSelectElement>("select");
      select.value = "feedback";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    type(message(), "More bot difficulty levels, please.");
    await submit();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/support");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body);
    expect(body).toMatchObject({ topic: "feedback", message: "More bot difficulty levels, please.",
                                 email: null, website: "" });
    expect(typeof body.version).toBe("string");
    expect(host.querySelector('[role="status"]')!.textContent).toContain("Thanks — we read every message.");
  });

  it("says so when the hourly limit is reached, and keeps the message", async () => {
    fetchMock.mockResolvedValue({ status: 429, json: async () => ({ detail: "rate_limited" }) });
    render();
    type(message(), "A second message this hour.");
    await submit();
    expect(q('[role="alert"]').textContent).toMatch(/try again later/);
    expect(message().value).toBe("A second message this hour.");
  });

  it("says so on a network error", async () => {
    fetchMock.mockRejectedValue(new TypeError("offline"));
    render();
    type(message(), "Sent while offline.");
    await submit();
    expect(q('[role="alert"]').textContent).toMatch(/Check your connection/);
    expect(send().disabled).toBe(false);
  });
});
