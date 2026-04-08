// ─────────────────────────────────────────────────────────────────────────────
// components/BankConnect.jsx
//
// UI para conectar bancos y ver balances por banco.
// Dos vistas: lista de bancos conectados + formulario de conexión.
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect } from "react";
import { C } from "../data/colors.js";
import * as api from "../services/api.js";

const fmt = (n) =>
  new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 }).format(n);

const fmtDate = (iso) => {
  if (!iso) return "Nunca";
  return new Date(iso).toLocaleDateString("es-CL", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

// ── Vista: lista de cuentas conectadas ────────────────────────────────────────

function AccountList({ accounts, totalBalance, onConnect, onSync, onDisconnect, syncing }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

      {/* Balance total */}
      {accounts.length > 0 && (
        <div style={{ background: `linear-gradient(135deg,${C.navy},#1a3a5c)`, borderRadius: 18, padding: "18px 20px", color: C.white }}>
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
      {accounts.map((acc) => (
        <div key={acc.id} style={{
          background: C.white, borderRadius: 16, padding: "14px 16px",
          border: `1px solid ${acc.status === "error" ? C.red : C.border}`,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ fontSize: 24 }}>{acc.bankIcon}</div>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>{acc.bankName}</div>
                <div style={{ fontSize: 11, color: C.textMuted, marginTop: 2 }}>
                  {acc.status === "error"
                    ? "⚠ Error de sync"
                    : `Actualizado: ${fmtDate(acc.lastSyncAt)}`}
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

          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button
              onClick={() => onSync(acc.id)}
              disabled={syncing === acc.id}
              style={{
                flex: 1, padding: "7px 0", borderRadius: 10,
                border: `1px solid ${C.border}`, background: "transparent",
                fontSize: 12, fontWeight: 600, color: C.textSecondary,
                cursor: syncing === acc.id ? "not-allowed" : "pointer",
                opacity: syncing === acc.id ? 0.6 : 1,
              }}
            >
              {syncing === acc.id ? "Sincronizando..." : "🔄 Sincronizar"}
            </button>
            <button
              onClick={() => onDisconnect(acc.id, acc.bankName)}
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
      ))}

      {/* Botón agregar banco */}
      <button
        onClick={onConnect}
        style={{
          padding: "14px", borderRadius: 16, border: `1.5px dashed ${C.border}`,
          background: "transparent", fontSize: 13, fontWeight: 600,
          color: C.textSecondary, cursor: "pointer", textAlign: "center",
        }}
      >
        + Conectar otro banco
      </button>

    </div>
  );
}

// ── Vista: formulario de conexión ─────────────────────────────────────────────

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
    // Auto-formatear RUT mientras escribe: 12345678-9
    const clean = v.replace(/[^0-9kK]/g, "");
    if (clean.length <= 1) return clean;
    const body     = clean.slice(0, -1);
    const dv       = clean.slice(-1).toUpperCase();
    const formatted = body.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    return `${formatted}-${dv}`;
  };

  const handleConnect = async () => {
    if (!selectedBank || !rut || !password) return;
    setLoading(true);
    setError("");

    try {
      const cleanRut = rut.replace(/\./g, "");
      await api.connectBank({ bankId: selectedBank.id, rut: cleanRut, password });
      onSuccess();
    } catch (e) {
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

        {/* Bancos disponibles */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {available.map((bank) => (
            <button
              key={bank.id}
              onClick={() => setSelectedBank(bank)}
              style={{
                display: "flex", alignItems: "center", gap: 12,
                padding: "14px 16px", borderRadius: 14,
                border: `1.5px solid ${C.green}`, background: "#f0fdf4",
                cursor: "pointer", textAlign: "left",
              }}
            >
              <span style={{ fontSize: 22 }}>{bank.icon}</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>{bank.name}</div>
                <div style={{ fontSize: 11, color: C.green, fontWeight: 600 }}>Disponible ahora</div>
              </div>
            </button>
          ))}
        </div>

        {/* Próximamente */}
        {coming.length > 0 && (
          <>
            <div style={{ fontSize: 11, color: C.textMuted, fontWeight: 600, marginTop: 4, letterSpacing: "0.05em", textTransform: "uppercase" }}>
              Próximamente
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {coming.map((bank) => (
                <div
                  key={bank.id}
                  style={{
                    display: "flex", alignItems: "center", gap: 12,
                    padding: "12px 16px", borderRadius: 14,
                    border: `1px solid ${C.border}`, background: C.white,
                    opacity: 0.6,
                  }}
                >
                  <span style={{ fontSize: 22 }}>{bank.icon}</span>
                  <div style={{ fontSize: 13, color: C.textSecondary }}>{bank.name}</div>
                </div>
              ))}
            </div>
          </>
        )}

        <button
          onClick={onCancel}
          style={{
            marginTop: 4, padding: "10px", borderRadius: 12,
            border: `1px solid ${C.border}`, background: "transparent",
            fontSize: 12, color: C.textSecondary, cursor: "pointer",
          }}
        >
          Cancelar
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

      {/* Header banco seleccionado */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 14px", background: "#f0fdf4", borderRadius: 12, border: `1px solid ${C.green}` }}>
        <span style={{ fontSize: 22 }}>{selectedBank.icon}</span>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.textPrimary }}>{selectedBank.name}</div>
          <div style={{ fontSize: 11, color: C.green }}>Ingresa tus credenciales</div>
        </div>
      </div>

      {/* Aviso de privacidad */}
      <div style={{ padding: "10px 12px", background: "#EFF6FF", borderRadius: 10, border: "1px solid #BFDBFE" }}>
        <div style={{ fontSize: 11.5, color: "#1E40AF", lineHeight: 1.5 }}>
          🔒 Tus credenciales se encriptan con AES-256 antes de guardarse. Sky nunca puede leerlas.
        </div>
      </div>

      {/* RUT */}
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, color: C.textSecondary, display: "block", marginBottom: 6 }}>
          RUT
        </label>
        <input
          type="text"
          value={rut}
          onChange={(e) => setRut(formatRut(e.target.value))}
          placeholder="12.345.678-9"
          maxLength={12}
          style={{
            width: "100%", padding: "11px 14px", borderRadius: 12,
            border: `1.5px solid ${C.border}`, fontSize: 14,
            color: C.textPrimary, outline: "none", fontFamily: "monospace",
            boxSizing: "border-box",
          }}
          onFocus={(e)  => (e.target.style.borderColor = C.green)}
          onBlur={(e)   => (e.target.style.borderColor = C.border)}
        />
      </div>

      {/* Clave */}
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, color: C.textSecondary, display: "block", marginBottom: 6 }}>
          Clave de internet
        </label>
        <div style={{ position: "relative" }}>
          <input
            type={showPass ? "text" : "password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            style={{
              width: "100%", padding: "11px 42px 11px 14px", borderRadius: 12,
              border: `1.5px solid ${C.border}`, fontSize: 14,
              color: C.textPrimary, outline: "none",
              boxSizing: "border-box",
            }}
            onFocus={(e)  => (e.target.style.borderColor = C.green)}
            onBlur={(e)   => (e.target.style.borderColor = C.border)}
            onKeyDown={(e) => e.key === "Enter" && handleConnect()}
          />
          <button
            type="button"
            onClick={() => setShowPass(!showPass)}
            style={{
              position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)",
              background: "none", border: "none", cursor: "pointer", fontSize: 16, padding: 0,
            }}
          >
            {showPass ? "🙈" : "👁️"}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div style={{ padding: "10px 12px", background: "#FEF2F2", borderRadius: 10, border: "1px solid #FECACA" }}>
          <div style={{ fontSize: 12, color: C.red }}>{error}</div>
        </div>
      )}

      {/* Botones */}
      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={() => { setSelectedBank(null); setError(""); setRut(""); setPassword(""); }}
          style={{
            padding: "11px 16px", borderRadius: 12,
            border: `1px solid ${C.border}`, background: "transparent",
            fontSize: 13, color: C.textSecondary, cursor: "pointer",
          }}
        >
          ← Volver
        </button>
        <button
          onClick={handleConnect}
          disabled={!rut || !password || loading}
          style={{
            flex: 1, padding: "11px 0", borderRadius: 12, border: "none",
            background: rut && password && !loading
              ? `linear-gradient(135deg,${C.green},${C.greenDark})`
              : C.border,
            color: C.white, fontSize: 13, fontWeight: 700,
            cursor: rut && password && !loading ? "pointer" : "not-allowed",
          }}
        >
          {loading ? "Conectando..." : "Conectar banco"}
        </button>
      </div>

    </div>
  );
}

// ── Componente principal ───────────────────────────────────────────────────────

export default function BankConnect({ onSyncComplete }) {
  const [view,        setView]        = useState("list"); // "list" | "connect"
  const [accounts,    setAccounts]    = useState([]);
  const [totalBalance,setTotalBalance]= useState(0);
  const [banks,       setBanks]       = useState([]);
  const [loading,     setLoading]     = useState(true);
  const [syncing,     setSyncing]     = useState(null);
  const [toast,       setToast]       = useState(null);

  const showToast = (msg, color = C.green) => {
    setToast({ msg, color });
    setTimeout(() => setToast(null), 3500);
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

  useEffect(() => { loadAccounts(); }, []);

  const handleSync = async (accountId) => {
    setSyncing(accountId);
    try {
      const result = await api.syncBankAccount(accountId);
      showToast(`✓ ${result.bankName}: ${result.newTransactions} transacciones nuevas`);
      await loadAccounts();
      onSyncComplete?.();
    } catch (e) {
      showToast(e.message || "Error al sincronizar", C.red);
    } finally {
      setSyncing(null);
    }
  };

  const handleDisconnect = async (accountId, bankName) => {
    if (!window.confirm(`¿Desconectar ${bankName}? Tu historial se conservará.`)) return;
    try {
      await api.disconnectBank(accountId);
      showToast(`${bankName} desconectado`);
      await loadAccounts();
    } catch (e) {
      showToast("Error al desconectar", C.red);
    }
  };

  const handleConnectSuccess = async () => {
    setView("list");
    showToast("Banco conectado. Sincronizando...");
    // Esperar un poco para que el sync inicial tenga tiempo
    setTimeout(async () => {
      await loadAccounts();
      onSyncComplete?.();
    }, 4000);
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

      {/* Toast */}
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
          syncing={syncing}
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