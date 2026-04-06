import { createClient } from "@supabase/supabase-js";

let _anon  = null;
let _admin = null;
let _aria  = null;

function init() {
  if (_anon && _admin && _aria) return;
  const url     = process.env.SUPABASE_URL;
  const anon    = process.env.SUPABASE_ANON_KEY;
  const service = process.env.SUPABASE_SERVICE_KEY;
  if (!url || !anon || !service) {
    throw new Error("[supabase] Faltan variables de entorno");
  }
  _anon  = createClient(url, anon);
  _admin = createClient(url, service, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
  _aria  = createClient(url, service, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

export function getAnonClient()  { init(); return _anon;  }
export function getAdminClient() { init(); return _admin; }
export function getAriaClient()  { init(); return _aria;  }