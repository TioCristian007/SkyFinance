// ─────────────────────────────────────────────────────────────────────────────
// routes/banking.js
//
// POST   /api/banking/connect        — conectar banco (encripta y guarda)
// POST   /api/banking/sync/:id       — sincronizar (responde INMEDIATO, corre en bg)
// POST   /api/banking/sync-all       — sincronizar todas
// GET    /api/banking/accounts       — listar cuentas + balances + estado
// GET    /api/banking/banks          — bancos disponibles
// DELETE /api/banking/accounts/:id   — desconectar (borra credenciales)
//
// SYNC ASÍNCRONO:
//   El sync de bchile puede tardar 2+ minutos esperando aprobación 2FA.
//   POST /sync/:id responde inmediatamente con { started: true }.
//   El frontend hace polling a GET /accounts cada 4s para ver el estado.
//   El campo last_sync_error muestra "⏳ Esperando aprobación..." durante el 2FA.
// ─────────────────────────────────────────────────────────────────────────────

import express from "express";
import { getAdminClient }                    from "../services/supabaseClient.js";
import { encrypt }                           from "../services/encryptionService.js";
import { getSupportedBanks, isBankSupported } from "../services/bankingAdapter.js";
import { syncBankAccount, syncAllUserAccounts, getBankBalances } from "../services/bankSyncService.js";

const router = express.Router();
const db     = () => getAdminClient();

// ── GET /banks ────────────────────────────────────────────────────────────────
router.get("/banks", (req, res) => {
  res.json({ banks: getSupportedBanks() });
});

// ── GET /accounts ─────────────────────────────────────────────────────────────
router.get("/accounts", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });
    res.json(await getBankBalances(uid));
  } catch (e) {
    console.error("[banking] GET accounts:", e.message);
    res.status(500).json({ error: "Error al cargar cuentas bancarias" });
  }
});

// ── POST /connect ─────────────────────────────────────────────────────────────
// Encripta RUT + clave, guarda en bank_accounts, lanza sync inicial en background
router.post("/connect", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });

    const { bankId, rut, password } = req.body;
    if (!bankId || !rut || !password) {
      return res.status(400).json({ error: "bankId, rut y password son requeridos" });
    }
    if (!isBankSupported(bankId)) {
      return res.status(400).json({ error: `Banco "${bankId}" no disponible` });
    }

    const cleanRut      = rut.replace(/\./g, "").replace(/\s/g, "").trim();
    const encryptedRut  = encrypt(cleanRut);
    const encryptedPass = encrypt(password);

    const bankInfo = getSupportedBanks().find((b) => b.id === bankId);
    const bankName = bankInfo?.name || bankId;
    const bankIcon = bankInfo?.icon || "🏦";

    // Upsert — actualiza si ya existe (reconexión), crea si es nueva
    const { data: existing } = await db()
      .from("bank_accounts")
      .select("id")
      .eq("user_id", uid)
      .eq("bank_id", bankId)
      .single();

    let accountId;

    if (existing) {
      const { data: updated, error } = await db()
        .from("bank_accounts")
        .update({
          encrypted_rut:   encryptedRut,
          encrypted_pass:  encryptedPass,
          status:          "active",
          last_sync_error: null,
          updated_at:      new Date().toISOString(),
        })
        .eq("id", existing.id)
        .select("id")
        .single();
      if (error) throw error;
      accountId = updated.id;
    } else {
      const { data: created, error } = await db()
        .from("bank_accounts")
        .insert({ user_id: uid, bank_id: bankId, bank_name: bankName, bank_icon: bankIcon, encrypted_rut: encryptedRut, encrypted_pass: encryptedPass, status: "active" })
        .select("id")
        .single();
      if (error) throw error;
      accountId = created.id;
    }

    // Responder ANTES de empezar el sync
    res.json({
      success:   true,
      accountId,
      bankId,
      bankName,
      bankIcon,
      message:   bankId === "bchile"
        ? "Banco conectado. Abre tu app Banco de Chile y aprueba la notificación cuando aparezca."
        : "Banco conectado. Sincronizando movimientos...",
    });

    // Sync inicial en background — no bloquea la respuesta HTTP
    syncBankAccount(accountId, uid).catch((e) => {
      console.error(`[banking] sync inicial falló (${bankId}):`, e.message);
    });

  } catch (e) {
    console.error("[banking] POST connect:", e.message);
    res.status(500).json({ error: "Error al conectar el banco" });
  }
});

// ── POST /sync/:id — ASÍNCRONO ────────────────────────────────────────────────
// Responde inmediatamente. El sync corre en background.
// Frontend hace polling a GET /accounts para ver el progreso.
router.post("/sync/:id", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });

    const { data: account } = await db()
      .from("bank_accounts")
      .select("id, bank_id, bank_name")
      .eq("id",      req.params.id)
      .eq("user_id", uid)
      .neq("status", "disconnected")
      .single();

    if (!account) return res.status(404).json({ error: "Cuenta no encontrada" });

    // Responder inmediatamente
    res.json({
      started:  true,
      accountId: account.id,
      bankId:   account.bank_id,
      bankName: account.bank_name,
      message:  account.bank_id === "bchile"
        ? "Sincronizando. Si tienes 2FA activo, aprueba la notificación en tu app Banco de Chile."
        : "Sincronizando movimientos...",
    });

    // Sync en background
    syncBankAccount(account.id, uid).catch((e) => {
      console.error(`[banking] sync falló (${account.bank_id}):`, e.message);
    });

  } catch (e) {
    console.error("[banking] POST sync:", e.message);
    res.status(500).json({ error: e.message || "Error al sincronizar" });
  }
});

// ── POST /sync-all ────────────────────────────────────────────────────────────
router.post("/sync-all", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });
    res.json(await syncAllUserAccounts(uid));
  } catch (e) {
    console.error("[banking] POST sync-all:", e.message);
    res.status(500).json({ error: "Error al sincronizar" });
  }
});

// ── DELETE /accounts/:id ──────────────────────────────────────────────────────
// Borra credenciales, conserva historial de transacciones
router.delete("/accounts/:id", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });

    const { error } = await db()
      .from("bank_accounts")
      .update({
        status:         "disconnected",
        encrypted_rut:  "REMOVED",
        encrypted_pass: "REMOVED",
        updated_at:     new Date().toISOString(),
      })
      .eq("id",      req.params.id)
      .eq("user_id", uid);

    if (error) throw error;
    res.json({ success: true, message: "Banco desconectado. Historial conservado." });
  } catch (e) {
    console.error("[banking] DELETE account:", e.message);
    res.status(500).json({ error: "Error al desconectar el banco" });
  }
});

export default router;