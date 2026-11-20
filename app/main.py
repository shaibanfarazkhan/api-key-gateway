"""ASGI application entry point."""

from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.quotes import router as quotes_router
from app.api.usage import router as usage_router
from app.core.config import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name)
app.include_router(admin_router)
app.include_router(quotes_router)
app.include_router(usage_router)
