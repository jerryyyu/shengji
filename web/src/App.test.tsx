import { renderToString } from "react-dom/server";
import { expect, it } from "vitest";
import App from "./App";

it("keeps the lobby usable before asking phone players to rotate for the table", () => {
  const html = renderToString(<App />);
  expect(html).toContain('class="panel lobby-panel"');
  expect(html).not.toContain('class="rotate-hint"');
  expect(html).toContain('aria-label="Room code"');
  expect(html).toContain('enterKeyHint="go"');
});
