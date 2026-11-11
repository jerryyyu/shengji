import { renderToString } from "react-dom/server";
import { expect, it } from "vitest";
import App from "./App";

it("draws the lobby upright, with no rotate prompt and no turned table", () => {
  const html = renderToString(<App />);
  expect(html).toContain('class="panel lobby-panel"');
  expect(html).not.toContain("rotate-hint");
  expect(html).toContain('class="app"');
  expect(html).toContain('aria-label="Room code"');
  expect(html).toContain('enterKeyHint="go"');
});
