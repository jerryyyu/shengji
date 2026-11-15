// Shared by every test file (vitest.config.ts setupFiles).
//
// Tests that call vi.resetModules() re-import the app for each test. A dynamic
// import still loading when the registry is reset (the idle prefetch of the
// offline server or of an on-demand page, a lazy component) goes on loading
// modules after the reset: a module it was part-way through evaluating is
// then evaluated a second time, and the next test's app can hold two copies
// of one store (the chip reading one guest name, the Join panel another).
// Every import a test started settles before the next test begins.
import { afterEach, beforeEach, vi } from "vitest";

afterEach(async () => {
  await vi.dynamicImportSettled();
});

beforeEach(async () => {
  await vi.dynamicImportSettled();
});
