// ─────────────────────────────────────────────────────────────────────────────
// App.jsx — Orquestador raíz
//
// Maneja tres estados:
//   "loading"    — verificando si hay sesión guardada (localStorage)
//   "auth"       — no hay sesión → mostrar AuthScreen
//   "onboarding" — sesión nueva, sin perfil → mostrar OnboardingScreen
//   "app"        — sesión activa con perfil → mostrar Sky
//
// La sesión persiste en localStorage — si el usuario ya inició sesión en
// este dispositivo, pasa directo a "app" sin ver la pantalla de login.
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect } from "react";
import { supabase, getProfile, onAuthStateChange } from "./services/supabase.js";
import AuthScreen       from "./components/AuthScreen.jsx";
import OnboardingScreen from "./components/OnboardingScreen.jsx";
import Sky              from "./Sky.jsx";
import { C } from "./data/colors.js";

export default function App() {
  const [appState, setAppState] = useState("loading"); // loading | auth | onboarding | app
  const [user,     setUser]     = useState(null);

  useEffect(() => {
    // 1. Verificar si hay sesión guardada al cargar
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      if (!session) {
        setAppState("auth");
        return;
      }
      await handleSession(session);
    });

    // 2. Escuchar cambios de auth (login, logout, token refresh, Google callback)
    const { data: { subscription } } = onAuthStateChange(async (event, session) => {
      if (event === "SIGNED_OUT") {
        setUser(null);
        setAppState("auth");
        return;
      }
      if (session) {
        await handleSession(session);
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  async function handleSession(session) {
    setUser(session.user);

    // Verificar si el usuario ya completó el onboarding
    const profile = await getProfile(session.user.id);

    if (!profile || !profile.display_name) {
      // Nuevo usuario o sin perfil — mostrar onboarding
      setAppState("onboarding");
    } else {
      // Usuario conocido con perfil — ir directo a la app
      setAppState("app");
    }
  }

  function handleOnboardingComplete() {
    setAppState("app");
  }

  // Pantalla de carga mientras Supabase verifica la sesión guardada
  if (appState === "loading") {
    return (
      <div style={{
        minHeight:      "100vh",
        background:     C.bg,
        display:        "flex",
        flexDirection:  "column",
        alignItems:     "center",
        justifyContent: "center",
        gap:            16,
        fontFamily:     "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      }}>
        <img
          src="/assets/sky-logo-transparent.png"
          alt="Sky"
          style={{ height: 40, objectFit: "contain", opacity: 0.9 }}
          onError={e => { e.target.style.display = "none"; }}
        />
        <div style={{ fontSize: 13, color: C.textMuted }}>Cargando...</div>
      </div>
    );
  }

  if (appState === "auth") {
    return <AuthScreen />;
  }

  if (appState === "onboarding") {
    return (
      <OnboardingScreen
        userId={user?.id}
        onComplete={handleOnboardingComplete}
      />
    );
  }

  // appState === "app"
  return <Sky userId={user?.id} userEmail={user?.email} />;
}
