// components/AuthScreen.jsx
// Pantalla de login y registro.
// Maneja email/contraseña y Google OAuth.
// La sesión persiste en localStorage — el usuario no vuelve a ver esta pantalla
// hasta que cierre sesión manualmente.

import { useState } from "react";
import { C } from "../data/colors.js";
import { signInWithEmail, signUpWithEmail, signInWithGoogle } from "../services/supabase.js";

export default function AuthScreen({ onAuth }) {
  const [mode,     setMode]     = useState("login"); // "login" | "register"
  const [email,    setEmail]    = useState("");
  const [password, setPassword] = useState("");
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState("");

  const handleEmail = async () => {
    if (!email.trim() || !password.trim()) {
      setError("Completa email y contraseña");
      return;
    }
    setLoading(true);
    setError("");
    try {
      if (mode === "login") {
        await signInWithEmail(email.trim(), password);
      } else {
        await signUpWithEmail(email.trim(), password);
      }
      // onAuth se dispara desde el listener de Supabase en App.jsx
    } catch (e) {
      const msg = e.message || "Error de autenticación";
      if (msg.includes("Invalid login"))    setError("Email o contraseña incorrectos");
      else if (msg.includes("already"))     setError("Este email ya tiene una cuenta. Inicia sesión.");
      else if (msg.includes("Password"))    setError("La contraseña debe tener al menos 6 caracteres");
      else                                  setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleGoogle = async () => {
    setLoading(true);
    setError("");
    try {
      await signInWithGoogle();
      // La página redirige a Google y vuelve — Supabase maneja el callback
    } catch (e) {
      setError("Error al conectar con Google");
      setLoading(false);
    }
  };

  const inputStyle = {
    width:        "100%",
    padding:      "13px 16px",
    borderRadius: 14,
    border:       `1.5px solid ${C.border}`,
    background:   C.bg,
    fontSize:     15,
    color:        C.textPrimary,
    outline:      "none",
    fontFamily:   "inherit",
    marginBottom: 12,
  };

  return (
    <div style={{
      minHeight:      "100vh",
      background:     C.bg,
      display:        "flex",
      alignItems:     "center",
      justifyContent: "center",
      padding:        20,
      fontFamily:     "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    }}>
      <div style={{
        width:        "100%",
        maxWidth:     400,
        background:   C.white,
        borderRadius: 28,
        padding:      "36px 32px",
        boxShadow:    "0 20px 60px rgba(0,0,0,0.12)",
      }}>

        {/* Logo */}
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <div style={{
            display:        "inline-flex",
            alignItems:     "center",
            justifyContent: "center",
            width:          56,
            height:         56,
            borderRadius:   18,
            background:     `linear-gradient(135deg, ${C.green}, ${C.greenDark})`,
            fontSize:       26,
            marginBottom:   14,
          }}>
            💸
          </div>
          <div style={{ fontSize: 26, fontWeight: 800, color: C.navy, letterSpacing: "-0.5px" }}>
            Sky Finance
          </div>
          <div style={{ fontSize: 14, color: C.textSecondary, marginTop: 6 }}>
            {mode === "login" ? "Bienvenido de vuelta" : "Crea tu cuenta"}
          </div>
        </div>

        {/* Google */}
        <button
          onClick={handleGoogle}
          disabled={loading}
          style={{
            width:        "100%",
            padding:      "13px",
            borderRadius: 14,
            border:       `1.5px solid ${C.border}`,
            background:   C.white,
            color:        C.textPrimary,
            fontSize:     14,
            fontWeight:   600,
            cursor:       loading ? "not-allowed" : "pointer",
            fontFamily:   "inherit",
            display:      "flex",
            alignItems:   "center",
            justifyContent: "center",
            gap:          10,
            marginBottom: 20,
            opacity:      loading ? 0.6 : 1,
          }}
        >
          <svg width="18" height="18" viewBox="0 0 48 48">
            <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
            <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
            <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
            <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.97 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
          </svg>
          Continuar con Google
        </button>

        {/* Divider */}
        <div style={{
          display:       "flex",
          alignItems:    "center",
          gap:           12,
          marginBottom:  20,
          color:         C.textMuted,
          fontSize:      12,
        }}>
          <div style={{ flex: 1, height: 1, background: C.border }} />
          o con email
          <div style={{ flex: 1, height: 1, background: C.border }} />
        </div>

        {/* Email + Password */}
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="tu@email.com"
          type="email"
          style={inputStyle}
          onFocus={(e) => (e.target.style.borderColor = C.green)}
          onBlur={(e)  => (e.target.style.borderColor = C.border)}
          onKeyDown={(e) => e.key === "Enter" && handleEmail()}
        />
        <input
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Contraseña"
          type="password"
          style={{ ...inputStyle, marginBottom: 20 }}
          onFocus={(e) => (e.target.style.borderColor = C.green)}
          onBlur={(e)  => (e.target.style.borderColor = C.border)}
          onKeyDown={(e) => e.key === "Enter" && handleEmail()}
        />

        {error && (
          <div style={{
            fontSize:     13,
            color:        "#C62828",
            background:   "#FFEBEE",
            borderRadius: 10,
            padding:      "10px 14px",
            marginBottom: 16,
          }}>
            ⚠ {error}
          </div>
        )}

        <button
          onClick={handleEmail}
          disabled={loading}
          style={{
            width:        "100%",
            padding:      "14px",
            borderRadius: 14,
            border:       "none",
            background:   loading ? C.border : `linear-gradient(135deg, ${C.green}, ${C.greenDark})`,
            color:        C.white,
            fontSize:     15,
            fontWeight:   700,
            cursor:       loading ? "not-allowed" : "pointer",
            fontFamily:   "inherit",
            marginBottom: 20,
          }}
        >
          {loading ? "Cargando..." : mode === "login" ? "Iniciar sesión" : "Crear cuenta"}
        </button>

        {/* Toggle mode */}
        <div style={{ textAlign: "center", fontSize: 13, color: C.textSecondary }}>
          {mode === "login" ? "¿No tienes cuenta? " : "¿Ya tienes cuenta? "}
          <button
            onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}
            style={{
              background:  "none",
              border:      "none",
              color:       C.green,
              fontWeight:  700,
              cursor:      "pointer",
              fontSize:    13,
              fontFamily:  "inherit",
            }}
          >
            {mode === "login" ? "Regístrate" : "Inicia sesión"}
          </button>
        </div>

      </div>
    </div>
  );
}
