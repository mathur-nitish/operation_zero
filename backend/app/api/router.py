"""Version 1 API router. Feature routers are included here as milestones land."""

from fastapi import APIRouter

from app.api import auth, health

api_v1_router = APIRouter()
api_v1_router.include_router(health.router)
api_v1_router.include_router(auth.router)
