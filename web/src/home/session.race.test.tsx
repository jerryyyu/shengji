// Response ordering for useCachedResource: only the newest load of a key is
// drawn and cached, whichever order the responses land in.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { cached, forgetHomeSession, useCachedResource } from "./session";

type V = { ok: boolean; value: string };
function deferred() {
  let resolve!: (v: V) => void;
  const promise = new Promise<V>((r) => { resolve = r; });
  return { promise, resolve };
}

function Probe({ load }: { load: () => Promise<V> }) {
  const { value, reload } = useCachedResource("race", load);
  return <><output>{value?.value ?? "none"}</output><button onClick={() => void reload()}>reload</button></>;
}

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  forgetHomeSession();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const shown = () => host.querySelector("output")!.textContent;

/** Mount (load 1 pending), pull (load 2 pending), then resolve in `order`. */
async function mountThenReload(order: "fresh-first" | "old-first") {
  const old = deferred();
  const fresh = deferred();
  const loads = [old, fresh];
  let n = 0;
  await act(async () => { root.render(<Probe load={() => loads[n++].promise} />); });
  await act(async () => { host.querySelector("button")!.click(); });
  expect(n).toBe(2);
  const steps = order === "fresh-first"
    ? [() => fresh.resolve({ ok: true, value: "fresh" }), () => old.resolve({ ok: true, value: "stale" })]
    : [() => old.resolve({ ok: true, value: "stale" }), () => fresh.resolve({ ok: true, value: "fresh" })];
  for (const step of steps) await act(async () => { step(); });
}

/** A remount reads the cache at once while its own load is still pending. */
async function remountFromCache() {
  act(() => root.unmount());
  root = createRoot(host);
  await act(async () => { root.render(<Probe load={() => new Promise<V>(() => {})} />); });
}

it("keeps the pull's fresh value when the slower mount-time load lands after it", async () => {
  await mountThenReload("fresh-first");
  expect(shown()).toBe("fresh");
  expect(cached<V>("race")?.value).toBe("fresh");
  await remountFromCache();
  expect(shown()).toBe("fresh");
});

it("ends fresh when the mount-time load lands first and the pull after it", async () => {
  await mountThenReload("old-first");
  expect(shown()).toBe("fresh");
  expect(cached<V>("race")?.value).toBe("fresh");
  await remountFromCache();
  expect(shown()).toBe("fresh");
});
