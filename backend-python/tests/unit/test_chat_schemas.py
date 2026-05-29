"""Tests de sky.api.schemas.chat — ChatTurn y ChatRequest.history."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from sky.api.schemas.chat import ChatRequest, ChatTurn


def _make_turn(role: str = "user", content: str = "Hola") -> dict:
    return {"role": role, "content": content}


# ── ChatTurn ──────────────────────────────────────────────────────────────────

def test_chat_turn_user_valid() -> None:
    t = ChatTurn(role="user", content="¿cuánto gasté?")
    assert t.role == "user"


def test_chat_turn_assistant_valid() -> None:
    t = ChatTurn(role="assistant", content="Gastaste $80.000 este mes.")
    assert t.role == "assistant"


def test_chat_turn_invalid_role() -> None:
    with pytest.raises(ValidationError):
        ChatTurn(role="system", content="x")


def test_chat_turn_empty_content_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatTurn(role="user", content="")


# ── ChatRequest.history ───────────────────────────────────────────────────────

def test_chat_request_history_none() -> None:
    req = ChatRequest(message="hola")
    assert req.history is None


def test_chat_request_history_empty_list() -> None:
    req = ChatRequest(message="hola", history=[])
    assert req.history == []


def test_chat_request_history_valid_turns() -> None:
    turns = [_make_turn("user", "Hola"), _make_turn("assistant", "Hola, ¿en qué te ayudo?")]
    req = ChatRequest(message="¿cuánto gasté?", history=turns)
    assert len(req.history) == 2  # type: ignore[arg-type]
    assert req.history[0].role == "user"  # type: ignore[index]


def test_chat_request_history_max_20() -> None:
    turns = [_make_turn("user", f"msg {i}") for i in range(20)]
    req = ChatRequest(message="siguiente", history=turns)
    assert len(req.history) == 20  # type: ignore[arg-type]


def test_chat_request_history_21_rejected() -> None:
    turns = [_make_turn("user", f"msg {i}") for i in range(21)]
    with pytest.raises(ValidationError):
        ChatRequest(message="siguiente", history=turns)
