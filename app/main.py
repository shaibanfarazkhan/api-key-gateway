"""ASGI application entry point. Routes will be added in a later phase."""

from fastapi import FastAPI

from app.core.config import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name)
