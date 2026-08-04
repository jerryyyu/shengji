import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",     // localStorage + a DOM for component tests later
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
