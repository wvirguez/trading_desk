from fastapi import APIRouter

from app.api.v1 import agents, health, market, quant, signals, stream

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(market.router)
api_router.include_router(quant.router)
api_router.include_router(agents.router)
api_router.include_router(signals.router)
api_router.include_router(stream.router)
