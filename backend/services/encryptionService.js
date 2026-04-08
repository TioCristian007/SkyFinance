// ─────────────────────────────────────────────────────────────────────────────
// services/encryptionService.js
//
// AES-256-GCM para credenciales bancarias.
//
// MODELO DE SEGURIDAD:
//   - La clave maestra vive SOLO en BANK_ENCRYPTION_KEY (.env del servidor)
//   - Supabase almacena el ciphertext — inútil sin la clave del servidor
//   - Cada campo encriptado tiene su propio IV aleatorio (nunca reusar IVs)
//   - GCM incluye autenticación (authTag) — detecta tampering
//   - Si un atacante roba la DB, no puede descifrar sin BANK_ENCRYPTION_KEY
//
// FORMATO ALMACENADO: "base64(iv):base64(authTag):base64(ciphertext)"
// ─────────────────────────────────────────────────────────────────────────────

import crypto from "crypto";

const ALGORITHM  = "aes-256-gcm";
const IV_LENGTH  = 16;   // 128 bits — recomendado para GCM
const TAG_LENGTH = 16;   // 128 bits — máximo de autenticación

// La clave se lee del entorno — nunca hardcodeada
function getMasterKey() {
  const raw = process.env.BANK_ENCRYPTION_KEY;
  if (!raw) throw new Error("[encryption] BANK_ENCRYPTION_KEY no está definida en .env");

  // Derivar 32 bytes (256 bits) desde la clave raw vía SHA-256
  // Esto permite cualquier longitud de clave en el .env
  return crypto.createHash("sha256").update(raw).digest();
}

// ── Encriptar ─────────────────────────────────────────────────────────────────
// Retorna string en formato "iv:authTag:ciphertext" (todo base64)

export function encrypt(plaintext) {
  if (!plaintext || typeof plaintext !== "string") {
    throw new Error("[encryption] plaintext debe ser string no vacío");
  }

  const key    = getMasterKey();
  const iv     = crypto.randomBytes(IV_LENGTH);
  const cipher = crypto.createCipheriv(ALGORITHM, key, iv, { authTagLength: TAG_LENGTH });

  const encrypted = Buffer.concat([
    cipher.update(plaintext, "utf8"),
    cipher.final(),
  ]);

  const authTag = cipher.getAuthTag();

  return [
    iv.toString("base64"),
    authTag.toString("base64"),
    encrypted.toString("base64"),
  ].join(":");
}

// ── Desencriptar ──────────────────────────────────────────────────────────────
// Recibe el string "iv:authTag:ciphertext" y retorna plaintext

export function decrypt(encryptedString) {
  if (!encryptedString || typeof encryptedString !== "string") {
    throw new Error("[encryption] encryptedString inválido");
  }

  const parts = encryptedString.split(":");
  if (parts.length !== 3) {
    throw new Error("[encryption] formato inválido — esperado iv:authTag:ciphertext");
  }

  const [ivB64, tagB64, cipherB64] = parts;

  const key       = getMasterKey();
  const iv        = Buffer.from(ivB64,    "base64");
  const authTag   = Buffer.from(tagB64,   "base64");
  const encrypted = Buffer.from(cipherB64,"base64");

  const decipher = crypto.createDecipheriv(ALGORITHM, key, iv, { authTagLength: TAG_LENGTH });
  decipher.setAuthTag(authTag);

  try {
    const decrypted = Buffer.concat([
      decipher.update(encrypted),
      decipher.final(),
    ]);
    return decrypted.toString("utf8");
  } catch {
    throw new Error("[encryption] fallo de autenticación — datos corruptos o clave incorrecta");
  }
}

// ── Test de integridad al arrancar ────────────────────────────────────────────
// Verifica que la clave esté disponible y que encrypt/decrypt funcionen
// Se llama desde server.js al iniciar

export function verifyEncryptionReady() {
  try {
    const test      = "sky_encryption_test_" + Date.now();
    const encrypted = encrypt(test);
    const decrypted = decrypt(encrypted);
    if (decrypted !== test) throw new Error("roundtrip falló");
    console.log("✅ [encryption] AES-256-GCM listo");
    return true;
  } catch (e) {
    console.error("❌ [encryption] ERROR:", e.message);
    return false;
  }
}