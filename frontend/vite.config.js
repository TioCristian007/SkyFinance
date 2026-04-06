import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Cualquier request a /api en el frontend se redirige al backend
      // Esto evita el error de CORS en desarrollo local
      "/api": {
        target: "http://localhost:3001",
        changeOrigin: true,
      },
    },
  },
});
