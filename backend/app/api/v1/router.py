from fastapi import APIRouter

from app.api.v1 import health, market, quant

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(market.router)
api_router.include_router(quant.router)
