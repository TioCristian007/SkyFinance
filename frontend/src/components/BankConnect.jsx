// ─────────────────────────────────────────────────────────────────────────────
// components/BankConnect.jsx
//
// UI de conexión bancaria con:
//   · Lista de cuentas conectadas con balance por banco
//   · Balance total consolidado
//   · Polling automático post-sync para ver resultado sin recargar
//   · Instrucciones 2FA claras para Banco de Chile
//   · Estado visual durante sincronización y espera de 2FA
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect, useRef } from "react";
import { C } from "../data/colors.js";
import * as api from "../services/api.js";

const fmt = (n) =>
  new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 }).format(n);

const fmtDate = (iso) => {
  if (!iso) return "Nunca";
  return new Date(iso).toLocaleDateString("es-CL", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
};

// Durante el 2FA el backend marca status="waiting_2fa" y escribe el
// mensaje en last_sync_error. Aceptamos cualquiera de las dos señales:
// la nueva (status) es autoritativa, la del error string es fallback
// por si el servidor corre una versión anterior del schema.
const is2FAWaiting = (acc) =>
  acc.status === "waiting_2fa" ||
  /Esperando aprobaci[oó]n/i.test(acc.lastSyncError || "");

const isSyncInFlight = (acc) =>
  acc.status === "syncing" || acc.status === "waiting_2fa";

// Logos reales de bancos chilenos
const BANK_LOGOS = {
  "Falabella":    { src: "/assets/banks/falabella.png",   bg: "#2D6B2D" },
  "de Chile":     { src: "/assets/banks/banco-chile.png", bg: "#1A237E" },
  "Banco Estado": { src: "/assets/banks/bancoestado.png", bg: "#D42B2B" },
  "Santander":    { src: "/assets/banks/santander.png",   bg: "#EC0000" },
  "BCI":          { src: "/assets/banks/bci.png",         bg: "#F5F5F5" },
};

const getBankLogo = (name = "") => {
  for (const [k, v] of Object.entries(BANK_LOGOS)) {
    if (name.includes(k)) return v;
  }
  return null;
};

/** Renderiza logo del banco o fallback al icono original */
const BankIcon = ({ name, icon, size = 36 }) => {
  const logo = getBankLogo(name);
  if (logo) {
    return (
      <div style={{
        width: size, height: size, borderRadius: size * 0.25,
        background: logo.bg, overflow: "hidden", flexShrink: 0,
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        <img
          src={logo.src} alt=""
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
          onError={e => {
            e.target.style.display = "none";
            e.target.parentNode.insertAdjacentHTML("beforeend",
              `<span style="font-size:${size * 0.6}px">${icon || "🏦"}</span>`
            );
          }}
        />
      </div>
    );
  }
  return <span style={{ fontSize: size * 0.6 }}>{icon || "🏦"}</span>;
};

// ── AccountList ───────────────────────────────────────────────────────────────

function AccountList({ accounts, totalBalance, onConnect, onSync, onDisconnect, syncingId }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

      {/* Balance total */}
      {accounts.length > 0 && (
        <div style={{
          background: `linear-gradient(135deg,${C.navy},#1a3a5c)`,
          borderRadius: 18, padding: "18px 20px", color: C.white,
        }}>
          <div style={{ fontSize: 11, opacity: 0.6, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 6 }}>
            Balance total bancario
          </div>
          <div style={{ fontSize: 28, fontWeight: 800 }}>{fmt(totalBalance)}</div>
          <div style={{ fontSize: 11, opacity: 0.5, marginTop: 4 }}>
            {accounts.length} {accounts.length === 1 ? "cuenta conectada" : "cuentas conectadas"}
          </div>
        </div>
      )}

      {/* Tarjetas por banco */}
      {accounts.map((acc) => {
        const waiting2FA = is2FAWaiting(acc);
        const isSyncing  = syncingId === acc.id;

        return (
          <div key={acc.id} style={{
            background:   C.white,
            borderRadius: 16,
            padding:      "14px 16px",
            border:       `1.5px solid ${waiting2FA ? C.amber : acc.status === "error" ? C.red : C.border}`,
            transition:   "border-color 0.3s",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <BankIcon name={acc.bankName} icon={acc.bankIcon} size={36} />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>{acc.bankName}</div>
                  <div style={{ fontSize: 11, marginTop: 2, color: waiting2FA ? C.amber : acc.status === "error" ? C.red : C.textMuted }}>
                    {waiting2FA
                      ? "Abre tu app Banco de Chile y aprueba"
                      : acc.status === "error"
                        ? `${acc.lastSyncError || "Error de conexión"}`
                        : `Actualizado: ${fmtDate(acc.lastSyncAt)}`
                    }
                  </div>
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 16, fontWeight: 800, color: acc.balance >= 0 ? C.textPrimary : C.red }}>
                  {fmt(acc.balance)}
                </div>
                <div style={{ fontSize: 10, color: C.textMuted }}>saldo</div>
              </div>
            </div>

            {/* Banner 2FA */}
            {waiting2FA && (
              <div style={{
                marginTop: 10, padding: "10px 12px",
                background: "#FFF8E6", borderRadius: 10,
                border: `1px solid ${C.amber}`,
                fontSize: 12, color: "#92400E", lineHeight: 1.5,
              }}>
                🔔 Banco de Chile está esperando que apruebes la solicitud en tu app.<br />
                Una vez que apruebes, la actualización continúa automáticamente.
              </div>
            )}

            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <button
                onClick={() => onSync(acc.id, acc.bankId)}
                disabled={isSyncing || waiting2FA}
                style={{
                  flex: 1, padding: "7px 0", borderRadius: 10,
                  border: `1px solid ${C.border}`, background: "transparent",
                  fontSize: 12, fontWeight: 600, color: C.textSecondary,
                  cursor: (isSyncing || waiting2FA) ? "not-allowed" : "pointer",
                  opacity: (isSyncing || waiting2FA) ? 0.5 : 1,
                }}
              >
                {isSyncing ? "Actualizando..." : "Actualizar"}
              </button>
              <button
                onClick={() => onDisconnect(acc.id, acc.bankName)}
                disabled={isSyncing}
                style={{
                  padding: "7px 12px", borderRadius: 10,
                  border: `1px solid ${C.border}`, background: "transparent",
                  fontSize: 12, color: C.textMuted, cursor: "pointer",
                }}
              >
                Desconectar
              </button>
            </div>
          </div>
        );
      })}

      {/* Agregar banco */}
      <button
        onClick={onConnect}
        style={{
          padding: "14px", borderRadius: 16,
          border: `1.5px dashed ${C.border}`, background: "transparent",
          fontSize: 13, fontWeight: 600, color: C.textSecondary,
          cursor: "pointer", textAlign: "center",
        }}
      >
        + Conectar otro banco
      </button>
    </div>
  );
}

// ── ConnectForm ───────────────────────────────────────────────────────────────

function ConnectForm({ banks, onSuccess, onCancel }) {
  const [selectedBank, setSelectedBank] = useState(null);
  const [rut,          setRut]          = useState("");
  const [password,     setPassword]     = useState("");
  const [loading,      setLoading]      = useState(false);
  const [error,        setError]        = useState("");
  const [showPass,     setShowPass]     = useState(false);

  const available = banks.filter((b) => b.available);
  const coming    = banks.filter((b) => !b.available);

  const formatRut = (v) => {
    const clean = v.replace(/[^0-9kK]/g, "");
    if (clean.length <= 1) return clean;
    const body = clean.slice(0, -1).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    const dv   = clean.slice(-1).toUpperCase();
    return `${body}-${dv}`;
  };

  const handleConnect = async () => {
    console.log("[ConnectForm] handleConnect click →", { bankId: selectedBank?.id, rutLen: rut.length, passLen: password.length });
    if (!selectedBank || !rut || !password) {
      console.warn("[ConnectForm] aborto: faltan campos");
      return;
    }
    setLoading(true); setError("");
    try {
      const cleanRut = rut.replace(/\./g, "");
      console.log("[ConnectForm] llamando api.connectBank...");
      const res = await api.connectBank({ bankId: selectedBank.id, rut: cleanRut, password });
      console.log("[ConnectForm] connectBank respondió:", res);
      onSuccess(selectedBank.id);
    } catch (e) {
      console.error("[ConnectForm] handleConnect error:", e);
      setError(e.message || "Error al conectar. Verifica tus credenciales.");
    } finally {
      setLoading(false);
    }
  };

  if (!selectedBank) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary, marginBottom: 4 }}>
          ¿Con qué banco quieres conectarte?
        </div>

        {available.map((bank) => (
          <button key={bank.id} onClick={() => setSelectedBank(bank)} style={{
            display: "flex", alignItems: "center", gap: 12,
            padding: "14px 16px", borderRadius: 14,
            border: `1.5px solid ${C.green}`, background: "#f0fdf4",
            cursor: "pointer", textAlign: "left",
          }}>
            <BankIcon name={bank.name} icon={bank.icon} size={34} />
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>{bank.name}</div>
              <div style={{ fontSize: 11, color: C.green, fontWeight: 600 }}>Disponible</div>
            </div>
          </button>
        ))}

        {coming.length > 0 && (
          <>
            <div style={{ fontSize: 11, color: C.textMuted, fontWeight: 600, marginTop: 4, letterSpacing: "0.05em", textTransform: "uppercase" }}>
              Próximamente
            </div>
            {coming.map((bank) => (
              <div key={bank.id} style={{
                display: "flex", alignItems: "center", gap: 12,
                padding: "12px 16px", borderRadius: 14,
                border: `1px solid ${C.border}`, background: C.white, opacity: 0.55,
              }}>
                <BankIcon name={bank.name} icon={bank.icon} size={30} />
                <div style={{ fontSize: 13, color: C.textSecondary }}>{bank.name}</div>
              </div>
            ))}
          </>
        )}

        <button onClick={onCancel} style={{
          marginTop: 4, padding: "10px", borderRadius: 12,
          border: `1px solid ${C.border}`, background: "transparent",
          fontSize: 12, color: C.textSecondary, cursor: "pointer",
        }}>
          Cancelar
        </button>
      </div>
    );
  }

  // Formulario de credenciales
  const isBchile = selectedBank.id === "bchile";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

      {/* Header banco */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 14px", background: "#f0fdf4", borderRadius: 12, border: `1px solid ${C.green}` }}>
        <BankIcon name={selectedBank.name} icon={selectedBank.icon} size={34} />
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>{selectedBank.name}</div>
          <div style={{ fontSize: 11, color: C.green }}>Ingresa tus credenciales</div>
        </div>
      </div>

      {/* Nota 2FA para bchile */}
      {isBchile && (
        <div style={{ padding: "10px 12px", background: "#FFF8E6", borderRadius: 10, border: `1px solid ${C.amber}` }}>
          <div style={{ fontSize: 12, color: "#92400E", lineHeight: 1.5 }}>
            Si tienes <strong>Banco de Chile Pass</strong> activo, recibirás una notificación en tu app para aprobar el acceso. Tendrás 2 minutos para aprobarla.
          </div>
        </div>
      )}

      {/* Aviso de seguridad */}
      <div style={{ padding: "10px 12px", background: "#EFF6FF", borderRadius: 10, border: "1px solid #BFDBFE" }}>
        <div style={{ fontSize: 11.5, color: "#1E40AF", lineHeight: 1.5 }}>
          Tus credenciales se cifran con AES-256 antes de guardarse. Sky no las almacena en texto plano.
        </div>
      </div>

      {/* RUT */}
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, color: C.textSecondary, display: "block", marginBottom: 6 }}>RUT</label>
        <input
          type="text" value={rut} onChange={(e) => setRut(formatRut(e.target.value))}
          placeholder="12.345.678-9" maxLength={12}
          style={{ width: "100%", padding: "11px 14px", borderRadius: 12, border: `1.5px solid ${C.border}`, fontSize: 14, color: C.textPrimary, outline: "none", fontFamily: "monospace", boxSizing: "border-box" }}
          onFocus={(e) => (e.target.style.borderColor = C.green)}
          onBlur={(e)  => (e.target.style.borderColor = C.border)}
        />
      </div>

      {/* Clave */}
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, color: C.textSecondary, display: "block", marginBottom: 6 }}>Clave de internet</label>
        <div style={{ position: "relative" }}>
          <input
            type={showPass ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            style={{ width: "100%", padding: "11px 42px 11px 14px", borderRadius: 12, border: `1.5px solid ${C.border}`, fontSize: 14, color: C.textPrimary, outline: "none", boxSizing: "border-box" }}
            onFocus={(e) => (e.target.style.borderColor = C.green)}
            onBlur={(e)  => (e.target.style.borderColor = C.border)}
            onKeyDown={(e) => e.key === "Enter" && handleConnect()}
          />
          <button type="button" onClick={() => setShowPass(!showPass)} style={{ position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", padding: 0, color: C.textMuted, display: "flex", alignItems: "center" }}>
            <svg viewBox="0 0 20 20" width="18" height="18" fill="none">
              {showPass
                ? <><path d="M2 10s3-6 8-6 8 6 8 6-3 6-8 6-8-6-8-6z" stroke="currentColor" strokeWidth="1.4"/><circle cx="10" cy="10" r="2.5" stroke="currentColor" strokeWidth="1.4"/><path d="M3 3l14 14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></>
                : <><path d="M2 10s3-6 8-6 8 6 8 6-3 6-8 6-8-6-8-6z" stroke="currentColor" strokeWidth="1.4"/><circle cx="10" cy="10" r="2.5" stroke="currentColor" strokeWidth="1.4"/></>
              }
            </svg>
          </button>
        </div>
      </div>

      {error && (
        <div style={{ padding: "10px 12px", background: "#FEF2F2", borderRadius: 10, border: "1px solid #FECACA" }}>
          <div style={{ fontSize: 12, color: C.red }}>{error}</div>
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={() => { setSelectedBank(null); setError(""); setRut(""); setPassword(""); }} style={{ padding: "11px 16px", borderRadius: 12, border: `1px solid ${C.border}`, background: "transparent", fontSize: 13, color: C.textSecondary, cursor: "pointer" }}>
          ← Volver
        </button>
        <button onClick={handleConnect} disabled={!rut || !password || loading} style={{ flex: 1, padding: "11px 0", borderRadius: 12, border: "none", background: rut && password && !loading ? `linear-gradient(135deg,${C.green},${C.greenDark})` : C.border, color: C.white, fontSize: 13, fontWeight: 700, cursor: rut && password && !loading ? "pointer" : "not-allowed" }}>
          {loading ? "Conectando..." : "Conectar banco"}
        </button>
      </div>
    </div>
  );
}

// ── BankConnect principal ─────────────────────────────────────────────────────

export default function BankConnect({ onSyncComplete }) {
  const [view,         setView]         = useState("list");
  const [accounts,     setAccounts]     = useState([]);
  const [totalBalance, setTotalBalance] = useState(0);
  const [banks,        setBanks]        = useState([]);
  const [loading,      setLoading]      = useState(true);
  const [syncingId,    setSyncingId]    = useState(null);
  const [toast,        setToast]        = useState(null);
  const pollingRef = useRef(null);

  const showToast = (msg, color = C.green) => {
    setToast({ msg, color });
    setTimeout(() => setToast(null), 4000);
  };

  const loadAccounts = async () => {
    try {
      const [accRes, banksRes] = await Promise.all([
        api.getBankAccounts(),
        api.getSupportedBanks(),
      ]);
      setAccounts(accRes.accounts || []);
      setTotalBalance(accRes.totalBalance || 0);
      setBanks(banksRes.banks || []);
    } catch (e) {
      console.error("[BankConnect] loadAccounts:", e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAccounts();
    return () => { if (pollingRef.current) clearInterval(pollingRef.current); };
  }, []);

  // Iniciar polling para ver resultado del sync asíncrono
  const startPolling = (accountId) => {
    if (pollingRef.current) clearInterval(pollingRef.current);
    let attempts      = 0;
    let lastSyncAtRef = null; // timestamp pre-sync, para detectar refresh
    pollingRef.current = setInterval(async () => {
      attempts++;
      await loadAccounts();

      setAccounts((prev) => {
        const acc = prev.find((a) => a.id === accountId);
        if (!acc) return prev;

        // Snapshot inicial del lastSyncAt — si cambia, sabemos que el
        // backend completó un ciclo nuevo (no estamos viendo el anterior).
        if (attempts === 1) lastSyncAtRef = acc.lastSyncAt || null;

        const is2FA    = is2FAWaiting(acc);
        const inFlight = isSyncInFlight(acc);
        // Done real: status active, lastSyncAt cambió respecto al snapshot,
        // y NO estamos esperando 2FA. Sin el check de cambio de timestamp,
        // el poll declara "listo" en el primer tick porque lee el estado
        // previo (active + un lastSyncAt viejo).
        const isDone   = acc.status === "active" &&
                         acc.lastSyncAt &&
                         acc.lastSyncAt !== lastSyncAtRef &&
                         !is2FA;
        const isError  = acc.status === "error" && !is2FA;
        const timeout  = attempts >= 50; // 50 × 4s = ~3.5 minutos

        if (isDone || isError || timeout) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
          setSyncingId(null);
          onSyncComplete?.();
          if (isDone)  showToast(`${acc.bankName} actualizado`);
          if (isError) showToast(acc.lastSyncError || "Error al actualizar", C.red);
          if (timeout && !isDone && !isError) {
            showToast("El sync está tardando demasiado. Revisa el banco.", C.amber);
          }
        } else if (inFlight) {
          // Mantener el spinner/disable durante el vuelo
          setSyncingId(accountId);
        }
        return prev;
      });
    }, 4000);
  };

  const handleSync = async (accountId, bankId) => {
    console.log("[BankConnect] handleSync click →", { accountId, bankId });
    setSyncingId(accountId);
    try {
      console.log("[BankConnect] llamando api.syncBankAccount...");
      const result = await api.syncBankAccount(accountId);
      console.log("[BankConnect] syncBankAccount respondió:", result);

      // El backend ahora SIEMPRE responde {started:true} y corre en background.
      // Arrancamos polling para ver el resultado en GET /accounts.
      if (result?.started || result?.success) {
        if (bankId === "bchile") {
          showToast("Aprueba la notificación en tu app Banco de Chile", C.amber);
        } else {
          showToast("Actualizando cuenta...");
        }
        startPolling(accountId);
        return;
      }

      // Fallback por si el backend respondió con algo inesperado
      await loadAccounts();
      onSyncComplete?.();
    } catch (e) {
      console.error("[BankConnect] handleSync error:", e);
      let msg = e.message || "Error al actualizar";
      if (/Chrome|Chromium/i.test(msg))   msg = "Servicio de conexión no disponible. Intenta más tarde.";
      if (/AUTH_FAILED/i.test(msg))        msg = "RUT o clave incorrectos. Reconecta el banco.";
      if (/2FA_TIMEOUT/i.test(msg))        msg = "No se recibió aprobación 2FA. Intenta nuevamente.";
      showToast(msg, C.red);
      setSyncingId(null);
    }
  };

  const handleDisconnect = async (accountId, bankName) => {
    console.log("[BankConnect] handleDisconnect click →", { accountId, bankName });
    if (!window.confirm(`¿Desconectar ${bankName}? Tu historial se conservará.`)) return;
    try {
      await api.disconnectBank(accountId);
      showToast(`${bankName} desconectado`);
      await loadAccounts();
    } catch (e) {
      console.error("[BankConnect] handleDisconnect error:", e);
      showToast("Error al desconectar", C.red);
    }
  };

  const handleConnectSuccess = async (bankId) => {
    console.log("[BankConnect] handleConnectSuccess →", bankId);
    setView("list");
    if (bankId === "bchile") {
      showToast("Banco conectado. Aprueba la notificación en tu app", C.amber);
    } else {
      showToast("Banco conectado. Actualizando...");
    }
    // Esperar un momento para que el sync de /connect escriba el registro
    // inicial, luego leer cuentas directamente y arrancar polling.
    // Antes usábamos setAccounts(prev => {...}) para leer el ID recién
    // creado, pero React batching hacía que prev estuviera stale y el
    // polling nunca arrancaba.
    setTimeout(async () => {
      try {
        const res = await api.getBankAccounts();
        const fresh = res.accounts || [];
        setAccounts(fresh);
        setTotalBalance(res.totalBalance || 0);
        const newAcc = fresh.find((a) => a.bankId === bankId);
        if (newAcc) {
          setSyncingId(newAcc.id);
          startPolling(newAcc.id);
        }
      } catch (e) {
        console.error("[BankConnect] post-connect refresh:", e.message);
      }
    }, 2000);
  };

  if (loading) {
    return (
      <div style={{ padding: "20px", textAlign: "center", color: C.textMuted, fontSize: 13 }}>
        Cargando cuentas...
      </div>
    );
  }

  return (
    <div style={{ padding: "14px 14px 28px", position: "relative" }}>
      {toast && (
        <div style={{
          position: "fixed", top: 18, left: "50%", transform: "translateX(-50%)", zIndex: 9999,
          padding: "10px 20px", borderRadius: 24, color: C.white, fontSize: 13, fontWeight: 700,
          background: toast.color, boxShadow: "0 8px 24px rgba(0,0,0,0.2)",
          animation: "slideDown 0.3s ease", whiteSpace: "nowrap",
        }}>
          {toast.msg}
        </div>
      )}

      {view === "list" ? (
        <AccountList
          accounts={accounts}
          totalBalance={totalBalance}
          onConnect={() => setView("connect")}
          onSync={handleSync}
          onDisconnect={handleDisconnect}
          syncingId={syncingId}
        />
      ) : (
        <ConnectForm
          banks={banks}
          onSuccess={handleConnectSuccess}
          onCancel={() => setView("list")}
        />
      )}
    </div>
  );
}