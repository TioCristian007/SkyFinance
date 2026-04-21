"""
Verificación standalone de compatibilidad encryption Node ↔ Python.

Uso:
    1. En Supabase, copiar un valor de bank_accounts.encrypted_rut
    2. Pegar abajo como NODE_TOKEN
    3. Poner el RUT esperado como EXPECTED
    4. Correr: python scripts/verify_encryption_compat.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from sky.core.encryption import decrypt

# ── CONFIGURAR ESTOS VALORES ──
NODE_TOKEN = "PEGAR_ENCRYPTED_RUT_DE_SUPABASE_AQUI"
EXPECTED = "RUT_ESPERADO"
RAW_KEY = os.getenv("BANK_ENCRYPTION_KEY", "")

if not RAW_KEY:
    print("❌ BANK_ENCRYPTION_KEY no está en el entorno")
    sys.exit(1)

if NODE_TOKEN == "PEGAR_ENCRYPTED_RUT_DE_SUPABASE_AQUI":
    print("⚠️  Configura NODE_TOKEN y EXPECTED antes de correr")
    sys.exit(1)

try:
    result = decrypt(NODE_TOKEN, RAW_KEY)
    if result == EXPECTED:
        print(f"✅ Compatibilidad verificada: '{result}'")
    else:
        print(f"❌ Decrypt OK pero valor distinto: got '{result}', expected '{EXPECTED}'")
        sys.exit(1)
except Exception as e:
    print(f"❌ Decrypt falló: {e}")
    sys.exit(1)
