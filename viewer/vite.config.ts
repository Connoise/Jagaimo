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
});
