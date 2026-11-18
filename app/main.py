"""ASGI application entry point."""

from fastapi import FastAPI

from app.core.config import get_settings
from app.api.admin import router as admin_router

settings = get_settings()
app = FastAPI(title=settings.app_name)
app.include_router(admin_router)
