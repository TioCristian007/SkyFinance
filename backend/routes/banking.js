// ─────────────────────────────────────────────────────────────────────────────
// routes/banking.js
//
// Endpoints para gestión de cuentas bancarias.
//
// POST   /api/banking/connect          ← conectar un banco (guarda credenciales encriptadas)
// POST   /api/banking/sync/:id         ← sincronizar una cuenta específica
// POST   /api/banking/sync-all         ← sincronizar todas las cuentas del usuario
// GET    /api/banking/accounts         ← listar cuentas con balances
// GET    /api/banking/banks            ← listar bancos disponibles
// DELETE /api/banking/accounts/:id     ← desconectar un banco (borra credenciales)
// ─────────────────────────────────────────────────────────────────────────────

import express from "express";
import { getAdminClient }    from "../services/supabaseClient.js";
import { encrypt }           from "../services/encryptionService.js";
import { getSupportedBanks, isBankSupported } from "../services/bankingAdapter.js";
import { syncBankAccount, syncAllUserAccounts, getBankBalances } from "../services/bankSyncService.js";

const router = express.Router();
const db     = () => getAdminClient();

// ── GET /api/banking/banks — bancos disponibles ───────────────────────────────
router.get("/banks", (req, res) => {
  res.json({ banks: getSupportedBanks() });
});

// ── GET /api/banking/accounts — cuentas conectadas + balances ────────────────
router.get("/accounts", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });

    const result = await getBankBalances(uid);
    res.json(result);
  } catch (e) {
    console.error("[banking] GET accounts:", e.message);
    res.status(500).json({ error: "Error al cargar cuentas bancarias" });
  }
});

// ── POST /api/banking/connect — conectar un banco ─────────────────────────────
// Body: { bankId, rut, password }
// Las credenciales se encriptan INMEDIATAMENTE y nunca se logean
router.post("/connect", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });

    const { bankId, rut, password } = req.body;

    // Validaciones
    if (!bankId || !rut || !password) {
      return res.status(400).json({ error: "bankId, rut y password son requeridos" });
    }

    if (!isBankSupported(bankId)) {
      return res.status(400).json({ error: `Banco "${bankId}" no disponible aún` });
    }

    // Limpiar RUT (remover puntos y espacios)
    const cleanRut = rut.replace(/\./g, "").replace(/\s/g, "").trim();

    // Encriptar inmediatamente — las credenciales en texto plano mueren aquí
    const encryptedRut  = encrypt(cleanRut);
    const encryptedPass = encrypt(password);

    // Info del banco para display
    const banks     = getSupportedBanks();
    const bankInfo  = banks.find((b) => b.id === bankId);
    const bankName  = bankInfo?.name || bankId;
    const bankIcon  = bankInfo?.icon || "🏦";

    // Verificar si ya existe (UNIQUE constraint en user_id + bank_id)
    const { data: existing } = await db()
      .from("bank_accounts")
      .select("id, status")
      .eq("user_id", uid)
      .eq("bank_id", bankId)
      .single();

    let accountId;

    if (existing) {
      // Actualizar credenciales de cuenta existente (reconexión)
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
      // Crear cuenta nueva
      const { data: created, error } = await db()
        .from("bank_accounts")
        .insert({
          user_id:        uid,
          bank_id:        bankId,
          bank_name:      bankName,
          bank_icon:      bankIcon,
          encrypted_rut:  encryptedRut,
          encrypted_pass: encryptedPass,
          status:         "active",
        })
        .select("id")
        .single();

      if (error) throw error;
      accountId = created.id;
    }

    // Responder inmediatamente — el sync inicial corre en background
    res.json({
      success:   true,
      accountId,
      bankId,
      bankName,
      bankIcon,
      message:   "Cuenta conectada. Sincronizando movimientos...",
    });

    // Sync inicial en background (no bloquea la respuesta)
    syncBankAccount(accountId, uid).catch((e) => {
      console.error(`[banking] sync inicial falló para ${bankId}:`, e.message);
    });

  } catch (e) {
    console.error("[banking] POST connect:", e.message);
    res.status(500).json({ error: "Error al conectar el banco" });
  }
});

// ── POST /api/banking/sync/:id — sincronizar una cuenta ──────────────────────
// El scraper tarda (bchile con 2FA puede llegar a 120s). Si esperamos en
// foreground, el fetch del browser timeoutea y el usuario nunca ve el
// resultado. Respondemos inmediatamente con {started:true} y dejamos que
// el sync corra en background — el frontend hace polling a GET /accounts
// para ver el estado actualizado (status, last_balance, last_sync_error).
router.post("/sync/:id", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });

    const accountId = req.params.id;

    // Validar dueño antes de disparar el sync — no queremos trabajar en
    // cuentas ajenas ni devolver 200 cuando el id no pertenece al usuario.
    const { data: acc, error: accErr } = await db()
      .from("bank_accounts")
      .select("id, bank_id, bank_name, status")
      .eq("id", accountId)
      .eq("user_id", uid)
      .single();

    if (accErr || !acc) {
      return res.status(404).json({ error: "Cuenta no encontrada" });
    }

    // Responder inmediatamente — el sync corre en background
    res.json({
      started:  true,
      accountId,
      bankId:   acc.bank_id,
      bankName: acc.bank_name,
      message:  "Sincronización iniciada",
    });

    // Fire-and-forget. Errores se guardan en bank_accounts.last_sync_error
    // y el frontend los lee en el próximo poll.
    syncBankAccount(accountId, uid).catch((e) => {
      console.error(`[banking] sync background falló:`, e.message);
    });
  } catch (e) {
    console.error("[banking] POST sync:", e.message);
    res.status(500).json({ error: e.message || "Error al sincronizar" });
  }
});

// ── POST /api/banking/sync-all — sincronizar todas ───────────────────────────
router.post("/sync-all", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });

    const result = await syncAllUserAccounts(uid);
    res.json(result);
  } catch (e) {
    console.error("[banking] POST sync-all:", e.message);
    res.status(500).json({ error: "Error al sincronizar cuentas" });
  }
});

// ── DELETE /api/banking/accounts/:id — desconectar banco ─────────────────────
// Elimina las credenciales encriptadas. Las transacciones históricas se conservan.
router.delete("/accounts/:id", async (req, res) => {
  try {
    const uid = req.userId;
    if (!uid) return res.status(401).json({ error: "No autenticado" });

    // Marcar como desconectada (conserva historial de transacciones)
    // Para borrar también las transacciones: cambiar a hard delete
    const { error } = await db()
      .from("bank_accounts")
      .update({
        status:         "disconnected",
        encrypted_rut:  "REMOVED",   // sobrescribir credenciales
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