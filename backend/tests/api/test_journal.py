"""Tests de `GET /api/v1/journal`."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.enums import SignalStatus
from app.schemas.journal import JournalSchema
from tests.api.test_paper import add_signal, execute_url

URL = "/api/v1/journal"

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("use_test_db")]


async def test_journal_vacio(client: AsyncClient, db_session: AsyncSession) -> None:
    response = await client.get(URL)

    assert response.status_code == 200
    journal = JournalSchema.model_validate(response.json())
    assert journal.entries == [] and journal.summary.n_signals == 0
    assert journal.summary.win_rate is None


async def test_journal_refleja_ejecucion_y_rechazo(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    executed = await add_signal(db_session)
    rejected = await add_signal(db_session, SignalStatus.REJECTED, symbol="BTC/USDT")
    await client.post(execute_url(executed.id))

    response = await client.get(URL)

    assert response.status_code == 200
    body = response.json()
    by_id = {e["signal_id"]: e for e in body["entries"]}
    assert by_id[str(executed.id)]["outcome"] == "PENDING_FILL"
    assert by_id[str(executed.id)]["signal_status"] == "EXECUTED"
    assert by_id[str(rejected.id)]["outcome"] == "NOT_EXECUTED"
    assert by_id[str(rejected.id)]["veto_reasons"] == ["RR_BELOW_MIN"]
    assert isinstance(by_id[str(executed.id)]["entry"], str)
    assert isinstance(by_id[str(executed.id)]["rr"], str)
    assert body["summary"]["n_signals"] == 2 and body["summary"]["n_executed"] == 1


async def test_journal_filtra_por_simbolo(client: AsyncClient, db_session: AsyncSession) -> None:
    await add_signal(db_session)
    await add_signal(db_session, symbol="BTC/USDT")

    body = (await client.get(URL, params={"symbol": "BTC/USDT"})).json()

    assert [e["symbol"] for e in body["entries"]] == ["BTC/USDT"]


async def test_journal_simbolo_desconocido_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.get(URL, params={"symbol": "XYZ"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Instrumento desconocido: XYZ"


@pytest.mark.parametrize("limit", [0, 501])
async def test_journal_rechaza_limit_fuera_de_rango(
    client: AsyncClient, db_session: AsyncSession, limit: int
) -> None:
    assert (await client.get(URL, params={"limit": limit})).status_code == 422
