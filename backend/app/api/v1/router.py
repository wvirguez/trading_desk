from fastapi import APIRouter

from app.api.v1 import agents, health, journal, market, paper, quant, signals, stream

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(market.router)
api_router.include_router(quant.router)
api_router.include_router(agents.router)
api_router.include_router(signals.router)
api_router.include_router(stream.router)
api_router.include_router(paper.router)
api_router.include_router(journal.router)
