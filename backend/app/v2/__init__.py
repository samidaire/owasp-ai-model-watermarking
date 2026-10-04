"""v2 API (API-03): authenticated, OpenAPI-documented resources under /api/v2."""
from fastapi import APIRouter

from . import accounts

api_router = APIRouter()
for _r in (accounts.router,):
    api_router.include_router(_r)
