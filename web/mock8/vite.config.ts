import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  root: new URL("..", import.meta.url).pathname,
  plugins: [react()],
  cacheDir: "/Users/jerryyu/.claude/jobs/d0498cda/tmp/flowfix/mock8/vitecache",
});
