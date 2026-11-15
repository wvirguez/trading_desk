"""Tests de `POST /api/v1/agents/analyze` (SSE). Sin red: el modelo se inyecta con FunctionModel.

Limitación (D87): `httpx.ASGITransport` no permite cortar la conexión a mitad de respuesta, así
que la desconexión del cliente se prueba (a) consumiendo el generador de cuerpo del endpoint y
cerrándolo, y (b) cancelando su tarea; ambos deben cerrar el generador del orquestador sin filas
a medias.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from pydantic import TypeAdapter
from pydantic_ai import ModelResponse
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.models import AgentRole, AgentsNotConfiguredError, ModelFactory
from app.api.v1 import agents as agents_api
from app.api.v1.agents import get_model_factory
from app.core.config import Settings, get_settings
from app.core.db import build_engine
from app.main import app
from app.models.agent_analysis import AgentAnalysis
from app.models.trade_signal import TradeSignal
from app.repositories import agent_analyses as steps_repo
from app.schemas.analysis import (
    AgentReportSchema,
    AnalysisCompleted,
    AnalysisEvent,
    AnalysisEventEnvelope,
    AnalysisFailed,
    AnalysisStarted,
    AnalyzeRequest,
)
from app.services.analysis import analyze
from tests.services.test_analysis_service import (
    APPROVE,
    factory_of,
    happy_factory,
    make_settings,
    quant_report,
    scripted,
    seed_world,
    structure_report,
    truth,
)

URL = "/api/v1/agents/analyze"
BODY = {"symbol": "EUR/USD"}
EVENTS: TypeAdapter[AnalysisEvent] = TypeAdapter(AnalysisEvent)

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("use_test_db")]


def use_factory(factory: ModelFactory, settings: Settings | None = None) -> None:
    app.dependency_overrides[get_model_factory] = lambda: factory
    app.dependency_overrides[get_settings] = lambda: settings or make_settings()


def inert_factory(role: AgentRole) -> Any:
    """Fábrica inofensiva para tests que fallan antes de invocar al modelo."""
    return scripted({})


def parse_sse(text: str) -> list[AnalysisEvent]:
    chunks = [c for c in text.split("\n\n") if c]
    assert all(c.startswith("data: ") for c in chunks), chunks
    return [EVENTS.validate_python(json.loads(c[len("data: ") :])) for c in chunks]


async def n_rows(session: AsyncSession, model: type[Any]) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def test_stream_camino_feliz(client: AsyncClient, db_session: AsyncSession) -> None:
    await seed_world(db_session)
    use_factory(happy_factory(await truth(db_session)))

    response = await client.post(URL, json=BODY)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert [e.event for e in events] == [
        "analysis_started",
        *[n for _ in range(5) for n in ("step_started", "step_completed")],
        "analysis_completed",
    ]
    assert [e.seq for e in events] == list(range(len(events)))
    assert isinstance(events[0], AnalysisStarted)
    last = events[-1]
    assert isinstance(last, AnalysisCompleted)
    AgentReportSchema.model_validate(last.report.model_dump(mode="json"))
    assert last.report.symbol == "EUR/USD"
    rows = await steps_repo.list_by_analysis(db_session, last.analysis_id)
    assert len(rows) == 5 and all(r.status == "OK" for r in rows)


async def test_404_simbolo_desconocido(client: AsyncClient, db_session: AsyncSession) -> None:
    use_factory(inert_factory)

    response = await client.post(URL, json={"symbol": "XYZ"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Instrumento desconocido: XYZ"}
    assert await n_rows(db_session, AgentAnalysis) == 0


async def test_422_datos_insuficientes_con_cantidades(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    use_factory(inert_factory)

    response = await client.post(URL, json=BODY)  # sin velas

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Datos insuficientes para EUR/USD 1h: 0 velas, se necesitan al menos 100."
    )
    assert await n_rows(db_session, AgentAnalysis) == 0


async def test_422_timeframe_fuera_de_timeframes(client: AsyncClient) -> None:
    response = await client.post(URL, json=BODY | {"timeframe": "1d", "timeframes": ["1h", "4h"]})

    assert response.status_code == 422
    assert "debe estar incluido en timeframes" in response.text


async def test_422_cuerpo_invalido(client: AsyncClient) -> None:
    assert (await client.post(URL, json=BODY | {"extra": 1})).status_code == 422


async def test_503_sin_clave_con_la_fabrica_por_defecto(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_world(db_session)
    sin_clave = Settings(_env_file=None, analysis_lookback_bars=300)  # type: ignore[call-arg]
    app.dependency_overrides[get_settings] = lambda: sin_clave

    response = await client.post(URL, json=BODY)

    assert response.status_code == 503
    assert response.json() == {
        "detail": "El análisis con agentes no está configurado: falta ANTHROPIC_API_KEY."
    }
    assert await n_rows(db_session, AgentAnalysis) == 0


async def test_503_cuando_la_fabrica_lanza(client: AsyncClient, db_session: AsyncSession) -> None:
    await seed_world(db_session)

    def factory(role: AgentRole) -> Any:
        raise AgentsNotConfiguredError("x")

    use_factory(factory)

    response = await client.post(URL, json=BODY)

    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


async def test_503_google_sin_clave_nombra_gemini_api_key(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_world(db_session)
    sin_clave = Settings(  # type: ignore[call-arg]
        _env_file=None,
        analysis_lookback_bars=300,
        agent_provider="google",
        agent_model="gemini-3.8-flash",
    )
    app.dependency_overrides[get_settings] = lambda: sin_clave

    response = await client.post(URL, json=BODY)

    assert response.status_code == 503
    assert response.json() == {
        "detail": "El análisis con agentes no está configurado: falta GEMINI_API_KEY."
    }


async def test_503_google_sin_modelo_nombra_agent_model(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_world(db_session)
    sin_modelo = Settings(  # type: ignore[call-arg]
        _env_file=None,
        analysis_lookback_bars=300,
        agent_provider="google",
        gemini_api_key="AIza-x",
    )
    app.dependency_overrides[get_settings] = lambda: sin_modelo

    response = await client.post(URL, json=BODY)

    assert response.status_code == 503
    assert response.json() == {
        "detail": "El análisis con agentes no está configurado: falta AGENT_MODEL."
    }


async def test_fallo_de_agente_es_analysis_failed_con_http_200(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    use_factory(
        factory_of(
            scripted(structure_report(t)),
            scripted(fail=RuntimeError("el proveedor devolvió 500")),
            scripted(APPROVE),
        )
    )

    response = await client.post(URL, json=BODY)

    assert response.status_code == 200
    events = parse_sse(response.text)
    assert [e.event for e in events[-2:]] == ["step_failed", "analysis_failed"]
    last = events[-1]
    assert isinstance(last, AnalysisFailed)
    assert "el proveedor devolvió 500" in last.error
    rows = await steps_repo.list_by_analysis(db_session, last.analysis_id)
    assert [(r.step, r.status) for r in rows] == [("STRUCTURE", "OK"), ("QUANT", "ERROR")]
    assert await n_rows(db_session, TradeSignal) == 0


async def test_no_se_filtra_la_clave(client: AsyncClient, db_session: AsyncSession) -> None:
    await seed_world(db_session)
    settings = make_settings()
    use_factory(happy_factory(await truth(db_session)), settings)

    response = await client.post(URL, json=BODY)

    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() not in response.text


# --- desconexión del cliente ------------------------------------------------------------


async def endpoint_body(factory: ModelFactory) -> AsyncIterator[bytes]:
    """Genera el cuerpo del stream igual que el endpoint, con una sesión propia de tests."""
    engine = build_engine(get_settings().test_database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            stream = await analyze(
                session, AnalyzeRequest(symbol="EUR/USD"), make_settings(), factory
            )
            async for chunk in agents_api.sse_body(stream):
                yield chunk
    finally:
        await engine.dispose()


async def test_cerrar_el_cuerpo_tras_un_paso_cancela_el_analisis(
    db_session: AsyncSession,
) -> None:
    await seed_world(db_session)
    body = endpoint_body(happy_factory(await truth(db_session)))

    first_ids: list[str] = []
    async for chunk in body:
        event = json.loads(chunk.decode().removeprefix("data: "))
        first_ids.append(event["analysis_id"])
        if event["event"] == "step_completed":
            break
    await body.aclose()

    rows = await steps_repo.list_by_analysis(db_session, first_ids[0])  # type: ignore[arg-type]
    assert [r.step for r in rows] == ["STRUCTURE"]
    assert await n_rows(db_session, TradeSignal) == 0


async def test_cancelar_la_tarea_durante_un_agente_no_deja_filas(
    db_session: AsyncSession,
) -> None:
    await seed_world(db_session)
    t = await truth(db_session)
    entered = asyncio.Event()

    async def hang(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        entered.set()
        await asyncio.sleep(60)
        raise AssertionError("no debía terminar")

    factory = factory_of(
        FunctionModel(hang),  # type: ignore[arg-type]
        scripted(quant_report(t)),
        scripted(APPROVE),
    )
    ids: list[str] = []

    async def consume() -> None:
        async for chunk in endpoint_body(factory):
            ids.append(json.loads(chunk.decode().removeprefix("data: "))["analysis_id"])

    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), timeout=10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await steps_repo.list_by_analysis(db_session, ids[0]) == []  # type: ignore[arg-type]
    assert await n_rows(db_session, TradeSignal) == 0


# --- OpenAPI ----------------------------------------------------------------------------


def test_openapi_publica_los_esquemas_y_text_event_stream() -> None:
    spec = app.openapi()

    schemas = spec["components"]["schemas"]
    for name in (
        "AnalyzeRequest",
        "AgentReportSchema",
        "TradeSignalSchema",
        "AnalysisStarted",
        "AnalysisCompleted",
        "AnalysisFailed",
        "StepStarted",
        "StepCompleted",
        "StepFailed",
        "AnalysisEventEnvelope",
    ):
        assert name in schemas, name
    ok = spec["paths"]["/api/v1/agents/analyze"]["post"]["responses"]["200"]
    assert "text/event-stream" in ok["content"]
    assert ok["content"]["text/event-stream"]["schema"]["$ref"] == (
        "#/components/schemas/AnalysisEventEnvelope"
    )
    envelope = schemas["AnalysisEventEnvelope"]
    assert envelope["discriminator"]["propertyName"] == "event"
    assert len(envelope["oneOf"]) == 6
    assert "application/json" not in ok["content"]
    assert "/api/v1/signals/active" in spec["paths"]


def test_envoltorio_serializa_igual_que_un_evento() -> None:
    """El envoltorio solo publica el tipo: no cambia el JSON de cada `data:` (D108)."""
    event = AnalysisFailed(analysis_id=uuid4(), seq=1, error="x")
    assert AnalysisEventEnvelope(event).model_dump_json() == event.model_dump_json()
