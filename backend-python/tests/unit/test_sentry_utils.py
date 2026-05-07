"""Tests unitarios de sky.core.sentry_utils — before_send pipeline."""
from __future__ import annotations

from unittest.mock import patch

from sky.core.sentry_utils import before_send

# ── Tests originales (1-9) ─────────────────────────────────────────────────────

def test_password_key_redacted() -> None:
    """Clave 'password' → valor [REDACTED]."""
    result = before_send({"password": "s3cr3t"}, {})
    assert result is not None
    assert result["password"] == "[REDACTED]"


def test_encrypted_rut_key_redacted() -> None:
    """Clave 'encrypted_rut' → [REDACTED] sin importar el valor."""
    result = before_send({"encrypted_rut": "iv:tag:cipher"}, {})
    assert result is not None
    assert result["encrypted_rut"] == "[REDACTED]"


def test_rut_key_redacted() -> None:
    """Clave 'rut' → [REDACTED] por KEY (no por valor)."""
    result = before_send({"rut": "12.345.678-9"}, {})
    assert result is not None
    assert result["rut"] == "[REDACTED]"


def test_anthropic_token_in_value_redacted() -> None:
    """String con token Anthropic → [REDACTED]."""
    result = before_send({"msg": "sk-ant-api03-ABC123defgh"}, {})
    assert result is not None
    assert result["msg"] == "[REDACTED]"


def test_short_sk_not_redacted() -> None:
    """Token demasiado corto (< 10 chars tras sk-) → NO redactado."""
    result = before_send({"msg": "sk-abc"}, {})
    assert result is not None
    assert result["msg"] == "sk-abc"


def test_rut_chileno_in_value_redacted() -> None:
    """String con RUT chileno en value → [REDACTED]."""
    result = before_send({"error": "error para 12.345.678-9"}, {})
    assert result is not None
    assert result["error"] == "[REDACTED]"


def test_clean_event_unchanged() -> None:
    """Evento sin PII → valores sin modificar."""
    event: dict = {"level": "error", "message": "divide by zero", "extra": {"count": 42}}
    result = before_send(event, {})
    assert result is not None
    assert result["level"] == "error"
    assert result["message"] == "divide by zero"
    assert result["extra"]["count"] == 42


def test_nested_dict_scrubbed() -> None:
    """PII en dict anidado → [REDACTED] recursivamente."""
    event: dict = {"data": {"password": "x"}}
    result = before_send(event, {})
    assert result is not None
    assert result["data"]["password"] == "[REDACTED]"


def test_exception_returns_none() -> None:
    """Si _scrub lanza excepción → before_send retorna None (fail-safe)."""
    with patch("sky.core.sentry_utils._scrub", side_effect=RuntimeError("boom")):
        result = before_send({"test": "event"}, {})
    assert result is None


# ── Tests nuevos (10-13): exception, breadcrumb, request, post-scrub ───────────

def test_exception_vars_password_scrubbed() -> None:
    """PII en exception.stacktrace.frames[].vars → [REDACTED]."""
    event: dict = {
        "exception": {
            "values": [{
                "stacktrace": {
                    "frames": [{"vars": {"password": "secret", "user": "alice"}}]
                }
            }]
        }
    }
    result = before_send(event, {})
    assert result is not None
    frames = result["exception"]["values"][0]["stacktrace"]["frames"]
    assert frames[0]["vars"]["password"] == "[REDACTED]"
    assert frames[0]["vars"]["user"] == "alice"  # dato no sensible intacto


def test_breadcrumb_authorization_scrubbed() -> None:
    """Breadcrumb con header Authorization (case variante) → [REDACTED] (case-insensitive)."""
    event: dict = {
        "breadcrumbs": {
            "values": [{"data": {"Authorization": "Bearer tok123", "url": "/api/chat"}}]
        }
    }
    result = before_send(event, {})
    assert result is not None
    data = result["breadcrumbs"]["values"][0]["data"]
    assert data["Authorization"] == "[REDACTED]"
    assert data["url"] == "/api/chat"  # dato no sensible intacto


def test_request_data_and_headers_scrubbed() -> None:
    """event['request']['data'] con rut + ['headers'] con Cookie → ambos [REDACTED]."""
    event: dict = {
        "request": {
            "data": {"rut": "12345678-9", "amount": 5000},
            "headers": {"Cookie": "session=abc", "Content-Type": "application/json"},
        }
    }
    result = before_send(event, {})
    assert result is not None
    assert result["request"]["data"]["rut"] == "[REDACTED]"
    assert result["request"]["data"]["amount"] == 5000
    assert result["request"]["headers"]["Cookie"] == "[REDACTED]"
    assert result["request"]["headers"]["Content-Type"] == "application/json"


def test_post_scrub_residual_drops_event() -> None:
    """Token Anthropic como CLAVE de dict sobrevive _scrub → post-check detecta → None."""
    # El token está como KEY del dict, no como valor.
    # _scrub no aplica regex a claves (solo a valores y nombres en _SCRUB_KEYS).
    # _event_contains_sensitive serializa a JSON y encuentra el token → descarta evento.
    event: dict = {"extra": {"sk-ant-api03-abc123xyzdef": "innocuous_value"}}
    result = before_send(event, {})
    assert result is None
