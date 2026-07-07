import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Renderer tests run under jsdom (window/KeyboardEvent/DOM); Electron main-process
// tests run under node. Pure-logic modules are deliberately free of native deps so
// they import cleanly here without hardware or native binaries.
export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    // Default to jsdom for the renderer tests. Electron main-process tests opt
    // into node with a `// @vitest-environment node` docblock at the top.
    environment: "jsdom",
    include: [
      "src/**/*.{test,spec}.{ts,tsx}",
      "electron/**/*.{test,spec}.{ts,tsx}",
    ],
    exclude: ["node_modules", "dist", "release"],
  },
});
