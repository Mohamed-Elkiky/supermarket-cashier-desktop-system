import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Electron loads the packaged build via file://, so asset URLs must be
// relative ("./") rather than absolute root-relative paths ("/").
export default defineConfig({
    base: "./",
    plugins: [react()],
    build: {
        outDir: "dist",
        emptyOutDir: true,
    },
    server: {
        port: 5173,
        strictPort: true,
    },
});
