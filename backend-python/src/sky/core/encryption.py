"""
sky.core.encryption — AES-256-GCM para credenciales bancarias.

COMPATIBILIDAD BINARIA CON NODE.JS:
    El backend Node actual cifra credenciales con el formato:
        base64(iv):base64(authTag):base64(ciphertext)
    La clave maestra se deriva como SHA-256 del raw BANK_ENCRYPTION_KEY.
    Este módulo reproduce EXACTAMENTE ese comportamiento para que
    Python pueda descifrar tokens producidos por Node y viceversa.

FORMATO ALMACENADO: "base64(iv):base64(authTag):base64(ciphertext)"

MODELO DE SEGURIDAD:
    - La clave maestra vive SOLO en BANK_ENCRYPTION_KEY (env del servidor).
    - Supabase almacena el ciphertext — inútil sin la clave.
    - Cada campo tiene su propio IV aleatorio (nunca reusar IVs).
    - GCM incluye autenticación (authTag) — detecta tampering.
"""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Constantes — deben coincidir con encryptionService.js de Node
_IV_LENGTH = 16   # 128 bits
_TAG_LENGTH = 16  # 128 bits — GCM default

# Cache de la clave derivada (se calcula una sola vez por proceso)
# Cache de claves derivadas (una por raw_key distinta)
_derived_keys: dict[str, bytes] = {}


def _get_master_key(raw_key: str) -> bytes:
    if raw_key not in _derived_keys:
        _derived_keys[raw_key] = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return _derived_keys[raw_key]


def encrypt(plaintext: str, raw_key: str) -> str:
    """
    Cifra un string con AES-256-GCM.

    Returns:
        String en formato "base64(iv):base64(authTag):base64(ciphertext)"
        Compatible byte-a-byte con el output de encryptionService.js de Node.
    """
    if not plaintext:
        raise ValueError("plaintext debe ser string no vacío")

    key = _get_master_key(raw_key)
    iv = os.urandom(_IV_LENGTH)

    aesgcm = AESGCM(key)
    # AESGCM.encrypt retorna ciphertext + tag concatenados
    ct_with_tag = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)

    # Separar ciphertext y authTag (últimos 16 bytes)
    ciphertext = ct_with_tag[:-_TAG_LENGTH]
    auth_tag = ct_with_tag[-_TAG_LENGTH:]

    return ":".join([
        base64.b64encode(iv).decode("ascii"),
        base64.b64encode(auth_tag).decode("ascii"),
        base64.b64encode(ciphertext).decode("ascii"),
    ])


def decrypt(encrypted_string: str, raw_key: str) -> str:
    """
    Descifra un string producido por encrypt() o por encryptionService.js de Node.

    Args:
        encrypted_string: formato "base64(iv):base64(authTag):base64(ciphertext)"
        raw_key: BANK_ENCRYPTION_KEY raw del env

    Returns:
        Plaintext original.

    Raises:
        ValueError: si el formato es inválido o la autenticación falla.
    """
    if not encrypted_string:
        raise ValueError("encrypted_string inválido")

    parts = encrypted_string.split(":")
    if len(parts) != 3:
        raise ValueError("formato inválido — esperado iv:authTag:ciphertext")

    iv_b64, tag_b64, cipher_b64 = parts

    key = _get_master_key(raw_key)
    iv = base64.b64decode(iv_b64)
    auth_tag = base64.b64decode(tag_b64)
    ciphertext = base64.b64decode(cipher_b64)

    aesgcm = AESGCM(key)

    # AESGCM.decrypt espera ciphertext + tag concatenados
    ct_with_tag = ciphertext + auth_tag

    try:
        plaintext_bytes = aesgcm.decrypt(iv, ct_with_tag, None)
        return plaintext_bytes.decode("utf-8")
    except Exception as exc:
        raise ValueError(
            "fallo de autenticación — datos corruptos o clave incorrecta"
        ) from exc


def verify_encryption_ready(raw_key: str) -> bool:
    """
    Test de integridad al arrancar.
    Verifica que encrypt/decrypt funcionan con la clave actual.
    """
    test_str = f"sky_encryption_test_{os.urandom(8).hex()}"
    encrypted = encrypt(test_str, raw_key)
    decrypted = decrypt(encrypted, raw_key)
    if decrypted != test_str:
        raise RuntimeError("encryption roundtrip falló")
    return True
