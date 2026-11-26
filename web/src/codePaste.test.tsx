// A pasted invite link in Play's code box reads as its code: the box holds
// four characters, so the link itself would keep only "HTTP".
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { codeFromLink } from "./codes";
import { CodeRow } from "./components/Lobby";

describe("codeFromLink", () => {
  it("takes the code from an invite link, any host, older parameters too", () => {
    expect(codeFromLink("https://playshengji.com/?code=ABCD")).toBe("ABCD");
    expect(codeFromLink("  https://playshengji.com/?code=abcd  ")).toBe("ABCD");
    expect(codeFromLink("playshengji.com/?code=K7Q2")).toBe("K7Q2");
    expect(codeFromLink("https://shengji.fly.dev/?room=WXYZ")).toBe("WXYZ");
    expect(codeFromLink("http://localhost:5173/?party=AB12&name=Mei")).toBe("AB12");
  });

  it("leaves anything else to paste as typed", () => {
    expect(codeFromLink("ABCD")).toBeNull();
    expect(codeFromLink("abcd efgh")).toBeNull();
    expect(codeFromLink("https://playshengji.com/")).toBeNull();
    expect(codeFromLink("https://playshengji.com/?code=AB")).toBeNull();
  });
});

describe("Play's code box", () => {
  let host: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  afterEach(() => { act(() => root.unmount()); host.remove(); });

  const paste = (text: string) => {
    const onCode = vi.fn();
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => root.render(<CodeRow disabled={false} code="" onCode={onCode} onJoin={() => {}} />));
    const input = host.querySelector<HTMLInputElement>(".room-input")!;
    const ev = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(ev, "clipboardData", { value: { getData: () => text } });
    act(() => { input.dispatchEvent(ev); });
    return { onCode, prevented: ev.defaultPrevented };
  };

  it("a pasted link becomes its code", () => {
    const { onCode, prevented } = paste("https://playshengji.com/?code=ABCD");
    expect(onCode).toHaveBeenCalledWith("ABCD");
    expect(prevented).toBe(true);
  });

  it("a pasted code pastes as usual", () => {
    const { onCode, prevented } = paste("WXYZ");
    expect(onCode).not.toHaveBeenCalled();
    expect(prevented).toBe(false);
  });
});
