import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Bind to all interfaces so the dev server is reachable over the tailnet.
// Production is a static build served by Caddy/nginx (V9); access control is
// the tailnet ACL — there is no app-level auth (single user, decision §2.11).
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
  },
  preview: {
    host: true,
    port: 4173,
  },
  build: {
    // Recharts/React share a dependency graph, so splitting React out creates a
    // circular chunk. Keep the React ecosystem together; split only the
    // independent heavy vendors (charts, supabase) for cacheability.
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("lightweight-charts")) return "charts";
          if (id.includes("@supabase")) return "supabase";
          return "vendor";
        },
      },
    },
  },
});
