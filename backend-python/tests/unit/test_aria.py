"""Tests de sky.domain.aria — pipeline ARIA v2."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sky.domain.aria import (
    AnonProfile,
    build_anon_profile,
    classify_behavior_shift,
    classify_blocker,
    classify_goal_type,
    classify_mindset,
    classify_motivation,
    classify_orientation,
    classify_stress,
    get_amount_bucket,
    get_goal_target_bucket,
    has_significant_content,
    track_behavioral_signal,
    track_goal_event,
    track_spending_event,
)

_DUMMY_PROFILE = AnonProfile(
    age_range="26-35",
    region="RM-Central",
    income_range="1M-2M",
    occupation="empleado",
)
_DUMMY_USER = "user-aria-test-1"


# ── Guard: no escribe si no hay consentimiento ────────────────────────────────

@pytest.mark.asyncio
@patch("sky.domain.aria.get_aria_client")
@patch("sky.domain.aria._has_aria_consent", new_callable=AsyncMock, return_value=False)
async def test_no_write_consent_false(mock_consent: AsyncMock, mock_aria: MagicMock) -> None:
    await track_spending_event(_DUMMY_PROFILE, {"amount": 10_000}, _DUMMY_USER)
    mock_aria.return_value.schema.assert_not_called()


@pytest.mark.asyncio
@patch("sky.domain.aria.get_aria_client")
async def test_no_write_user_id_none(mock_aria: MagicMock) -> None:
    await track_spending_event(_DUMMY_PROFILE, {"amount": 10_000}, None)
    mock_aria.assert_not_called()


@pytest.mark.asyncio
@patch("sky.domain.aria.get_aria_client")
@patch("sky.domain.aria._has_aria_consent", new_callable=AsyncMock, return_value=False)
async def test_no_write_goal_event_consent_false(mock_consent: AsyncMock, mock_aria: MagicMock) -> None:
    await track_goal_event(_DUMMY_PROFILE, {"title": "Viaje Europa", "target_amount": 2_000_000}, user_id=_DUMMY_USER)
    mock_aria.return_value.schema.assert_not_called()


# ── Guard: escribe con consentimiento ─────────────────────────────────────────

@pytest.mark.asyncio
@patch("sky.domain.aria._has_aria_consent", new_callable=AsyncMock, return_value=True)
@patch("sky.domain.aria.get_aria_client")
async def test_write_when_consent_true(mock_aria: MagicMock, mock_consent: AsyncMock) -> None:
    mock_table = MagicMock()
    mock_aria.return_value.schema.return_value.from_.return_value = mock_table

    await track_spending_event(_DUMMY_PROFILE, {"amount": 10_000, "category": "food"}, _DUMMY_USER)

    mock_table.insert.assert_called_once()
    inserted = mock_table.insert.call_args[0][0]
    assert inserted["amount_bucket"] == "0-50k"
    assert inserted["category"] == "food"
    assert inserted["source"] == "manual"
    assert "batch_id" in inserted


# ── Amount buckets ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("amount,expected_bucket", [
    (0,          "0-50k"),
    (-100,       "0-50k"),
    (50_000,     "0-50k"),
    (50_001,     "50k-150k"),
    (150_000,    "50k-150k"),
    (150_001,    "150k-500k"),
    (500_000,    "150k-500k"),
    (500_001,    "500k-1.5M"),
    (1_500_000,  "500k-1.5M"),
    (1_500_001,  "1.5M+"),
    (5_000_000,  "1.5M+"),
])
def test_amount_bucket(amount: int, expected_bucket: str) -> None:
    assert get_amount_bucket(amount) == expected_bucket


@pytest.mark.parametrize("amount,expected", [
    (None,       None),
    (0,          None),
    (500_000,    "0-500k"),
    (2_000_000,  "500k-2M"),
    (10_000_000, "2M-10M"),
    (30_000_000, "10M-30M"),
    (30_000_001, "30M+"),
])
def test_goal_target_bucket(amount: int | None, expected: str | None) -> None:
    assert get_goal_target_bucket(amount) == expected


# ── Randomization ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("sky.domain.aria._has_aria_consent", new_callable=AsyncMock, return_value=True)
@patch("sky.domain.aria.get_aria_client")
async def test_amount_noise_in_bucket_range(mock_aria: MagicMock, mock_consent: AsyncMock) -> None:
    mock_table = MagicMock()
    mock_aria.return_value.schema.return_value.from_.return_value = mock_table

    await track_spending_event(_DUMMY_PROFILE, {"amount": 200_000}, _DUMMY_USER)

    inserted = mock_table.insert.call_args[0][0]
    assert inserted["amount_bucket"] == "150k-500k"
    assert 150_001 <= inserted["amount_noise"] <= 500_000


# ── Classifier: regex matches ─────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("tengo un fondo de emergencia",              "security"),
    ("quiero un viaje a Europa",                  "experience"),
    ("mi familia es lo más importante",           "family"),
    ("quiero independizarme y vivir solo",        "freedom"),
    ("quiero un auto nuevo bien lujoso",          "status"),
    ("compré una pizza hoy",                      "unknown"),
])
def test_classify_motivation(text: str, expected: str) -> None:
    assert classify_motivation(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("fue un impulso, no pude resistir",                   "impulse"),
    ("todos mis amigos fueron a la fiesta",                "social_pressure"),
    ("no me alcanza el sueldo nunca",                      "income_gap"),
    ("es mi hábito, siempre lo hago así",                  "habit"),
    ("no sé nada de finanzas, no entiendo",                "knowledge"),
    ("hoy almorcé con mi equipo del trabajo",              "unknown"),
])
def test_classify_blocker(text: str, expected: str) -> None:
    assert classify_blocker(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("quiero ahorrar y tener un fondo",            "saver"),
    ("plata es para gastarla, yolo",               "spender"),
    ("evito mirar mis gastos, me da miedo",        "avoider"),
    ("estoy bien con mis finanzas este mes",       "balanced"),
])
def test_classify_mindset(text: str, expected: str) -> None:
    assert classify_mindset(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("estoy muy preocupado, no veo salida",     "high"),
    ("estoy tranquilo y ordenado con la plata", "low"),
    ("más o menos, voy al día",                 "medium"),
])
def test_classify_stress(text: str, expected: str) -> None:
    assert classify_stress(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("necesito esto antes de fin de mes urgente", "short_term"),
    ("planeo para mi jubilación a largo plazo",   "long_term"),
    ("no sé bien qué quiero",                     "mixed"),
])
def test_classify_orientation(text: str, expected: str) -> None:
    assert classify_orientation(text) == expected


@pytest.mark.parametrize("title,expected", [
    ("comprar departamento propio",    "housing"),
    ("auto nuevo para el trabajo",     "vehicle"),
    ("viaje a Tailandia",              "travel"),
    ("fondo de emergencia",            "emergency"),
    ("matrimonio con mi pareja",       "life_event"),
    ("inversión en acciones",          "investment"),
    ("educación universitaria",        "education"),
    ("ahorrar para el verano",         "other"),
])
def test_classify_goal_type(title: str, expected: str) -> None:
    assert classify_goal_type(title) == expected


@pytest.mark.parametrize("user_msg,reply,expected", [
    ("voy a intentar gastar menos",  "",               "positive"),
    ("tiene sentido lo que decís",   "",               "positive"),
    ("no puedo cambiar mis hábitos", "",               "negative"),
    ("no me ayuda para nada",        "",               "negative"),
    ("ok",                           "",               "neutral"),
])
def test_classify_behavior_shift(user_msg: str, reply: str, expected: str) -> None:
    assert classify_behavior_shift(user_msg, reply) == expected


# ── has_significant_content ───────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("no tengo plata para pagar la deuda de este mes", True),
    ("quiero ahorrar para mi meta de ahorro bancario",  True),
    ("hola",                                           False),
    ("qué tal el tiempo hoy",                          False),
    ("gracias",                                        False),
])
def test_has_significant_content(text: str, expected: bool) -> None:
    assert has_significant_content(text) == expected


# ── behavioral_signal: 0 writes con texto sin contenido financiero ────────────

@pytest.mark.asyncio
@patch("sky.domain.aria._has_aria_consent", new_callable=AsyncMock, return_value=True)
@patch("sky.domain.aria.get_aria_client")
async def test_no_write_non_financial_text(mock_aria: MagicMock, mock_consent: AsyncMock) -> None:
    mock_table = MagicMock()
    mock_aria.return_value.schema.return_value.from_.return_value = mock_table

    await track_behavioral_signal(_DUMMY_PROFILE, "hola qué tal", "", _DUMMY_USER)

    mock_table.insert.assert_not_called()


# ── build_anon_profile ────────────────────────────────────────────────────────

def test_build_anon_profile_valid() -> None:
    p = build_anon_profile({
        "age_range": "26-35",
        "region": "Región Metropolitana",
        "income_range": "1M-2M",
        "occupation": "empleado",
    })
    assert p.age_range == "26-35"
    assert p.region == "RM-Central"
    assert p.income_range == "1M-2M"
    assert p.occupation == "empleado"


def test_build_anon_profile_unknown_defaults() -> None:
    p = build_anon_profile({})
    assert p.age_range == "unknown"
    assert p.region == "unknown"
    assert p.income_range == "unknown"
    assert p.occupation == "unknown"
