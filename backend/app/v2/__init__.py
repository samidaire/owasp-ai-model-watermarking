"""v2 API (API-03): authenticated, OpenAPI-documented resources under /api/v2."""
from fastapi import APIRouter

from . import accounts, models_routes, registry_routes, verification_routes

api_router = APIRouter()
for _r in (accounts.router, models_routes.router, registry_routes.router, verification_routes.router,):
    api_router.include_router(_r)
