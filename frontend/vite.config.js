import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En dev: el proxy /api → localhost:3001 evita CORS localmente y permite
//   que api.js use "/api" como base (sin VITE_API_URL).
// En build: Vite inyecta VITE_API_URL al bundle; api.js la usa.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:3001",
        changeOrigin: true,
      },
    },
  },
  preview: {
    // Permite previews en Railway con cualquier host (vite preview bloquea
    // hosts no listados por defecto en v5+).
    host: true,
    allowedHosts: true,
  },
});
