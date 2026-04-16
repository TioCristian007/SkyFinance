// ─────────────────────────────────────────────────────────────────────────────
// scripts/runScheduledSync.js
//
// Entry point para el cron job de Railway.
// Ejecuta runScheduledSync() una vez y termina con exit code 0/1.
//
// Cómo configurar en Railway:
//   1. En tu proyecto Railway, crea un nuevo servicio "cron".
//   2. Connect to the same GitHub repo, Root Directory: backend.
//   3. En Settings → Cron Schedule, ingresa: "0 * * * *"  (cada hora en punto).
//   4. Override Start Command con: node scripts/runScheduledSync.js
//   5. Las MISMAS variables de entorno que el servicio backend principal:
//        ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY,
//        BANK_ENCRYPTION_KEY, CHROME_PATH=/usr/bin/chromium, etc.
//
// El cron Service de Railway usa el mismo Dockerfile, así que Chromium
// y Playwright/Puppeteer están disponibles automáticamente.
//
// Alternativa sin Railway cron (si tu plan no lo incluye):
//   Usa cron-job.org (gratis) apuntando a POST /api/internal/scheduled-sync
//   con header x-cron-secret. El endpoint está en routes/internal.js.
// ─────────────────────────────────────────────────────────────────────────────

import dotenv from "dotenv";
dotenv.config();

import { runScheduledSync } from "../services/schedulerService.js";
import { verifyEncryptionReady } from "../services/encryptionService.js";

async function main() {
  console.log(`[cron] iniciando scheduled sync — ${new Date().toISOString()}`);

  // Verificación de salud antes de tocar nada.
  // Si BANK_ENCRYPTION_KEY no está, no podemos descifrar credenciales,
  // así que abortamos con exit code 1 para que el cron lo marque como fallido.
  try {
    verifyEncryptionReady();
  } catch (e) {
    console.error("[cron] encryption no lista:", e.message);
    process.exit(1);
  }

  const result = await runScheduledSync();

  if (result.error) {
    console.error("[cron] terminó con error:", result.error);
    process.exit(1);
  }

  console.log(`[cron] OK — ${JSON.stringify(result)}`);
  process.exit(0);
}

main().catch((e) => {
  console.error("[cron] uncaught:", e);
  process.exit(1);
});
