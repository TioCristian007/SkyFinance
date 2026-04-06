// ─────────────────────────────────────────────────────────────────────────────
// services/supabase.js
//
// Cliente de Supabase para el frontend.
// Maneja auth, sesiones persistentes y Google OAuth.
//
// La sesión se guarda en localStorage automáticamente — el usuario
// no tiene que hacer login cada vez que abre la app en el mismo dispositivo.
// ─────────────────────────────────────────────────────────────────────────────

import { createClient } from "@supabase/supabase-js";

const SUPABASE_URL  = import.meta.env.VITE_SUPABASE_URL;
const SUPABASE_ANON = import.meta.env.VITE_SUPABASE_ANON_KEY;

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON, {
  auth: {
    // Persiste la sesión en localStorage — el usuario queda logueado
    // entre visitas sin tener que volver a ingresar credenciales
    persistSession:    true,
    autoRefreshToken:  true,
    detectSessionInUrl: true, // necesario para el callback de Google OAuth
    storage: localStorage,
  },
});

// ── Auth helpers ──────────────────────────────────────────────────────────────

export async function signUpWithEmail(email, password) {
  const { data, error } = await supabase.auth.signUp({ email, password });
  if (error) throw error;
  return data;
}

export async function signInWithEmail(email, password) {
  const { data, error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) throw error;
  return data;
}

export async function signInWithGoogle() {
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: `${window.location.origin}`,
    },
  });
  if (error) throw error;
}

export async function signOut() {
  const { error } = await supabase.auth.signOut();
  if (error) throw error;
}

export async function getSession() {
  const { data } = await supabase.auth.getSession();
  return data.session;
}

export function onAuthStateChange(callback) {
  return supabase.auth.onAuthStateChange((event, session) => {
    callback(event, session);
  });
}

// ── Profile helpers ───────────────────────────────────────────────────────────

export async function getProfile(userId) {
  const { data, error } = await supabase
    .from("profiles")
    .select("*")
    .eq("id", userId)
    .single();

  if (error && error.code !== "PGRST116") throw error; // PGRST116 = no rows
  return data || null;
}

export async function upsertProfile(userId, updates) {
  const { data, error } = await supabase
    .from("profiles")
    .upsert({ id: userId, ...updates, updated_at: new Date().toISOString() })
    .select()
    .single();

  if (error) throw error;
  return data;
}
