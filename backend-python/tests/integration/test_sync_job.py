"""
Integration test del job sync_bank_account.

Requiere:
    - DB de staging con tabla `bank_accounts` y `transactions`
    - Redis local (o fakeredis con ARQ)
    - Una cuenta de test con credenciales válidas (skip si no está configurada)
"""
import os

import pytest


@pytest.mark.skipif(
    not os.getenv("INTEGRATION_TEST_BANK_ACCOUNT_ID"),
    reason="No INTEGRATION_TEST_BANK_ACCOUNT_ID env var; salteando integration test",
)
@pytest.mark.asyncio
async def test_sync_persists_movements_and_enqueues_categorize() -> None:
    # TODO(equipo): cuando tengamos cuenta de test con creds válidas, poblar:
    #   1. Crear bank_account con creds reales
    #   2. Llamar sync_bank_account
    #   3. Verificar transactions insertadas con categorization_status='pending'
    #   4. Llamar categorize_pending_job
    #   5. Verificar que pasaron a 'done' o 'failed'
    pytest.skip("Pendiente — requiere cuenta de test con creds válidas")
