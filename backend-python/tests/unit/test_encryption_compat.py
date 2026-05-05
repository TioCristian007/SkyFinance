"""
Test de compatibilidad binaria: Python puede descifrar tokens de Node.js y viceversa.

GATE BLOQUEANTE (Fase 3): si este test falla, NO se puede hacer cutover.
Los usuarios existentes tienen credenciales cifradas por Node.js en Supabase.
Python DEBE poder descifrarlas sin re-encriptar.

Para generar fixtures:
    En el backend Node actual, correr:
        const { encrypt } = require('./services/encryptionService.js');
        console.log(encrypt("12345678-9"));
        console.log(encrypt("mi_clave_secreta"));
    Copiar los outputs como FIXTURES abajo.
"""

import pytest

from sky.core.encryption import decrypt, encrypt, verify_encryption_ready

# Clave de test — NUNCA usar en producción
TEST_KEY = "test_key_for_unit_tests_only_32chars!"


class TestEncryptionRoundtrip:
    """Encrypt → decrypt debe devolver el plaintext original."""

    def test_basic_roundtrip(self):
        plaintext = "12345678-9"
        encrypted = encrypt(plaintext, TEST_KEY)
        assert decrypt(encrypted, TEST_KEY) == plaintext

    def test_format_is_three_parts(self):
        encrypted = encrypt("hello", TEST_KEY)
        parts = encrypted.split(":")
        assert len(parts) == 3, f"Expected 3 parts, got {len(parts)}: {encrypted}"

    def test_different_ivs_each_time(self):
        """Cada encrypt genera IV distinto — mismo plaintext, distinto ciphertext."""
        a = encrypt("same_input", TEST_KEY)
        b = encrypt("same_input", TEST_KEY)
        assert a != b  # IVs diferentes
        assert decrypt(a, TEST_KEY) == decrypt(b, TEST_KEY) == "same_input"

    def test_wrong_key_fails(self):
        encrypted = encrypt("secret", TEST_KEY)
        with pytest.raises(ValueError, match="fallo de autenticación"):
            decrypt(encrypted, "wrong_key_completely_different!!")

    def test_tampered_ciphertext_fails(self):
        encrypted = encrypt("secret", TEST_KEY)
        parts = encrypted.split(":")
        # Corromper el ciphertext
        tampered = parts[0] + ":" + parts[1] + ":AAAA" + parts[2][4:]
        with pytest.raises(ValueError):
            decrypt(tampered, TEST_KEY)

    def test_empty_plaintext_raises(self):
        with pytest.raises(ValueError):
            encrypt("", TEST_KEY)

    def test_unicode_roundtrip(self):
        plaintext = "contraseña_con_ñ_y_émojis_🔐"
        encrypted = encrypt(plaintext, TEST_KEY)
        assert decrypt(encrypted, TEST_KEY) == plaintext

    def test_verify_ready(self):
        assert verify_encryption_ready(TEST_KEY) is True


class TestNodeCompatibility:
    """
    Fixtures producidas por encryptionService.js de Node.
    INSTRUCCIONES: correr en Node con tu BANK_ENCRYPTION_KEY de test:

        process.env.BANK_ENCRYPTION_KEY = "test_key_for_unit_tests_only_32chars!";
        const { encrypt } = await import('./services/encryptionService.js');
        console.log("RUT:", encrypt("12345678-9"));
        console.log("PASS:", encrypt("mi_clave_secreta"));

    Pegar los outputs como fixtures.
    """

    # TODO: reemplazar con outputs reales de Node
    # Una vez generados, este test garantiza compatibilidad binaria permanente.

    def test_decrypt_node_rut(self):
        # Fixture generado con Node.js encryptionService.js + TEST_KEY
        node_encrypted = "hGqY/cS+axpHYuwpiq3A0Q==:p8RpECLwJflRvXQFLZqU+Q==:GJ8thEEHzUuf+A=="
        key = "test_key_for_unit_tests_only_32chars!"
        assert decrypt(node_encrypted, key) == "12345678-9"

    def test_decrypt_node_password(self):
        # Fixture generado con Node.js encryptionService.js + TEST_KEY
        node_encrypted = (
            "2Q2Nh6RtVmRB2fkhyb7C1w==:RXYvRwFKLaSupgjGCEEhNw==:7KXxA8tydNo5ZHmUKuWb4Q=="
        )
        key = "test_key_for_unit_tests_only_32chars!"
        assert decrypt(node_encrypted, key) == "mi_clave_secreta"
