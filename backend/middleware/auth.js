// ─────────────────────────────────────────────────────────────────────────────
// middleware/auth.js
//
// Lee el userId desde el header x-user-id y lo adjunta a req.userId.
// Todas las rutas usan req.userId — nunca más DEV_USER_ID.
//
// En producción esto se reemplazará por verificación del JWT de Supabase.
// Por ahora confía en el header porque el frontend solo lo manda
// cuando hay sesión activa de Supabase Auth.
// ─────────────────────────────────────────────────────────────────────────────

export function extractUserId(req, res, next) {
  const userId = req.headers["x-user-id"] || null;
  req.userId = userId;
  next();
}
