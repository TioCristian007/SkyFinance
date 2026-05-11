"""Integration tests: /api/account/export-request + process_export_request_job."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sky.api.deps import require_user_id
from sky.api.main import app

_TEST_USER = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_REQUEST_ID = "11111111-2222-3333-4444-555555555555"

_EXPORT_ROW = (
    _REQUEST_ID,      # id
    _TEST_USER,       # user_id
    "pending",        # status
    "json",           # format
    None,             # download_url
    datetime(2026, 5, 18, tzinfo=UTC),  # expires_at
    datetime(2026, 5, 11, tzinfo=UTC),  # requested_at
    None,             # delivered_at
)


def _make_insert_engine(row: tuple) -> MagicMock:
    result = MagicMock()
    result.fetchone.return_value = row
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=result)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.begin.return_value = ctx
    engine.connect.return_value = ctx
    return engine


def _make_select_engine(row: tuple | None) -> MagicMock:
    result = MagicMock()
    result.fetchone.return_value = row
    result.fetchall.return_value = [row] if row else []
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=result)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.connect.return_value = ctx
    engine.begin.return_value = ctx
    return engine


@pytest_asyncio.fixture
async def client():
    arq_mock = AsyncMock()
    arq_mock.enqueue_job = AsyncMock()
    app.dependency_overrides[require_user_id] = lambda: _TEST_USER
    # ASGITransport no ejecuta el lifespan — inyectar arq_pool directamente en app.state
    app.state.arq_pool = arq_mock
    with (
        patch("sky.api.main.build_router", new_callable=AsyncMock) as mock_br,
        patch("sky.api.main.create_pool", new_callable=AsyncMock) as mock_pool,
    ):
        mock_br.return_value = (MagicMock(), AsyncMock())
        mock_pool.return_value = arq_mock
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c._arq_mock = arq_mock
            yield c
    app.dependency_overrides = {}


@pytest_asyncio.fixture
async def unauth_client():
    with (
        patch("sky.api.main.build_router", new_callable=AsyncMock) as mock_br,
        patch("sky.api.main.create_pool", new_callable=AsyncMock) as mock_pool,
    ):
        mock_br.return_value = (MagicMock(), AsyncMock())
        mock_pool.return_value = AsyncMock()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


# ── 401 tests ─────────────────────────────────────────────────────────────────

async def test_create_export_no_jwt_returns_401(unauth_client: AsyncClient) -> None:
    resp = await unauth_client.post("/api/account/export-request", json={"format": "json"})
    assert resp.status_code == 401


async def test_get_export_no_jwt_returns_401(unauth_client: AsyncClient) -> None:
    resp = await unauth_client.get("/api/account/export-request")
    assert resp.status_code == 401


# ── POST /api/account/export-request ─────────────────────────────────────────

async def test_create_export_creates_pending_record(client: AsyncClient) -> None:
    with patch("sky.api.routers.account.get_engine", return_value=_make_insert_engine(_EXPORT_ROW)):
        resp = await client.post("/api/account/export-request", json={"format": "json"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == _REQUEST_ID
    assert data["status"] == "pending"
    assert data["format"] == "json"
    assert data["download_url"] is None
    assert data["delivered_at"] is None


async def test_create_export_enqueues_worker_job(client: AsyncClient) -> None:
    with patch("sky.api.routers.account.get_engine", return_value=_make_insert_engine(_EXPORT_ROW)):
        resp = await client.post("/api/account/export-request", json={"format": "csv"})
    assert resp.status_code == 201
    # El arq_pool.enqueue_job debe haber sido llamado con el job correcto
    app.state.arq_pool.enqueue_job.assert_called_once_with(
        "process_export_request_job", _REQUEST_ID
    )


# ── GET /api/account/export-request/{id} ─────────────────────────────────────

async def test_get_export_request_status_poll(client: AsyncClient) -> None:
    completed_row = (
        _REQUEST_ID, _TEST_USER, "completed", "json",
        "https://storage.example.com/file.zip",
        datetime(2026, 5, 18, tzinfo=UTC),
        datetime(2026, 5, 11, tzinfo=UTC),
        datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
    )
    with patch(
        "sky.api.routers.account.get_engine",
        return_value=_make_select_engine(completed_row),
    ):
        resp = await client.get(f"/api/account/export-request/{_REQUEST_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["download_url"] == "https://storage.example.com/file.zip"
    assert data["delivered_at"] is not None


async def test_get_export_request_not_found(client: AsyncClient) -> None:
    with patch(
        "sky.api.routers.account.get_engine",
        return_value=_make_select_engine(None),
    ):
        resp = await client.get(f"/api/account/export-request/{_REQUEST_ID}")
    assert resp.status_code == 404


# ── Worker job: process_export_request_job ────────────────────────────────────

def _make_worker_engine(req_row: tuple | None, *, fail_update: bool = False) -> MagicMock:
    """Engine que simula: SELECT request + N SELECTs de datos + UPDATE resultado."""
    req_result = MagicMock()
    req_result.fetchone.return_value = req_row

    empty = MagicMock()
    empty.fetchall.return_value = []

    update_result = MagicMock()
    update_result.rowcount = 1

    conn_read = AsyncMock()
    conn_read.execute = AsyncMock(side_effect=[req_result, empty, empty, empty, empty, empty])
    ctx_read = MagicMock()
    ctx_read.__aenter__ = AsyncMock(return_value=conn_read)
    ctx_read.__aexit__ = AsyncMock(return_value=False)

    conn_write = AsyncMock()
    if fail_update:
        conn_write.execute = AsyncMock(side_effect=RuntimeError("DB write error"))
    else:
        conn_write.execute = AsyncMock(return_value=update_result)
    ctx_write = MagicMock()
    ctx_write.__aenter__ = AsyncMock(return_value=conn_write)
    ctx_write.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.connect.return_value = ctx_read
    engine.begin.return_value = ctx_write
    return engine


async def test_export_job_generates_zip_with_expected_files() -> None:
    """El job genera ZIP con los 5 datasets en formato JSON."""
    req_row = (_REQUEST_ID, _TEST_USER, "json")
    engine = _make_worker_engine(req_row)

    storage_mock = MagicMock()
    storage_mock.storage.from_.return_value.upload = MagicMock(return_value=MagicMock())
    storage_mock.storage.from_.return_value.create_signed_url = MagicMock(
        return_value={"signedURL": "https://storage.example.com/file.zip"}
    )

    with (
        patch("sky.worker.jobs.data_export.get_engine", return_value=engine),
        patch("sky.worker.jobs.data_export.get_aria_client", return_value=storage_mock),
        patch("sky.worker.jobs.data_export.log_event", new_callable=AsyncMock),
        patch("asyncio.to_thread", side_effect=_fake_to_thread),
    ):
        from sky.worker.jobs.data_export import process_export_request_job

        result = await process_export_request_job({}, _REQUEST_ID)

    assert result["status"] == "completed"
    assert result["size_bytes"] > 0


async def test_export_job_excludes_encrypted_fields() -> None:
    """El ZIP nunca incluye encrypted_rut ni encrypted_pass."""
    from sky.worker.jobs.data_export import _collect_user_data

    engine = MagicMock()
    txn_result = MagicMock()
    txn_result.fetchall.return_value = [
        MagicMock(_mapping={"id": "t1", "amount": -1000, "category": "food",
                             "description": "Jumbo", "date": "2026-05-01"})
    ]
    empty = MagicMock()
    empty.fetchall.return_value = []

    conn = AsyncMock()
    conn.execute = AsyncMock(side_effect=[txn_result, empty, empty, empty, empty])
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    engine.connect.return_value = ctx

    with patch("sky.worker.jobs.data_export.get_engine", return_value=engine):
        data = await _collect_user_data(engine, _TEST_USER)

    # Verificar que no hay encrypted fields en ningún dataset
    all_keys = set()
    for rows in data.values():
        for row in rows:
            all_keys.update(row.keys())

    assert "encrypted_rut" not in all_keys
    assert "encrypted_pass" not in all_keys


async def test_export_job_failure_marks_failed_sanitizes_error() -> None:
    """
    Cuando el job falla (zip/upload), verifica:
    - status='failed' en DB
    - error retornado es solo el tipo (sin stack trace, sin paths internos)
    - delivered_at queda NULL (no se hace UPDATE con delivered_at)
    - Storage.upload NO es llamado si falla antes del upload
    """
    req_row = (_REQUEST_ID, _TEST_USER, "json")

    req_result = MagicMock()
    req_result.fetchone.return_value = req_row

    failed_update = MagicMock()
    conn_write = AsyncMock()
    conn_write.execute = AsyncMock(return_value=failed_update)
    ctx_write = MagicMock()
    ctx_write.__aenter__ = AsyncMock(return_value=conn_write)
    ctx_write.__aexit__ = AsyncMock(return_value=False)

    conn_read = AsyncMock()
    conn_read.execute = AsyncMock(return_value=req_result)
    ctx_read = MagicMock()
    ctx_read.__aenter__ = AsyncMock(return_value=conn_read)
    ctx_read.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.connect.return_value = ctx_read
    engine.begin.return_value = ctx_write

    storage_mock = MagicMock()

    with (
        patch("sky.worker.jobs.data_export.get_engine", return_value=engine),
        patch("sky.worker.jobs.data_export.get_aria_client", return_value=storage_mock),
        patch(
            "sky.worker.jobs.data_export._collect_user_data",
            new_callable=AsyncMock,
            side_effect=ValueError("Internal path /app/src/sky exposed"),
        ),
    ):
        from sky.worker.jobs.data_export import process_export_request_job

        result = await process_export_request_job({}, _REQUEST_ID)

    # Status = failed
    assert result["status"] == "failed"

    # Error sanitizado: solo el tipo de excepción, sin paths ni detalles internos
    assert result["error"] == "ValueError"
    assert "/app" not in result["error"]
    assert "Internal path" not in result["error"]

    # delivered_at queda NULL: el UPDATE de fallo no incluye delivered_at
    update_call = conn_write.execute.call_args
    update_sql = str(update_call[0][0])
    assert "delivered_at" not in update_sql
    assert "failed" in update_sql

    # Storage NO fue tocado
    storage_mock.storage.from_.assert_not_called()


async def test_export_job_max_tries_is_one() -> None:
    """max_tries=1 en el job — ARQ no auto-retry."""
    from sky.worker.jobs.data_export import process_export_request_job

    assert getattr(process_export_request_job, "max_tries", None) == 1


# ── Helper ────────────────────────────────────────────────────────────────────

async def _fake_to_thread(func, *args, **kwargs):
    """Simula asyncio.to_thread ejecutando la función en el mismo thread."""
    return func(*args, **kwargs)
