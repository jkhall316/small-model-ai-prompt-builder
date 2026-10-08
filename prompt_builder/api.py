"""FastAPI router. Mount it in your own app (any prefix) or let server.py serve it standalone."""
from __future__ import annotations

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from . import core
from .settings import Settings


def create_router(settings: Settings | None = None, prefix: str | None = None) -> APIRouter:
    settings = settings or Settings.from_env()
    router = APIRouter(prefix=prefix if prefix is not None else settings.prefix)

    def _err(ex: core.PBError):
        body = {"error": str(ex)}
        if ex.raw:
            body["raw"] = ex.raw
        return JSONResponse(body, ex.status)

    @router.get("/tidy/status")
    def status():
        return core.status(settings)

    @router.get("/config")
    def config():
        return settings.public()

    @router.post("/tidy")
    def tidy(body: dict = Body(...)):
        try:
            return core.tidy(settings, body)
        except core.PBError as ex:
            return _err(ex)

    @router.post("/chat")
    def chat(body: dict = Body(...)):
        try:
            return core.chat(settings, body)
        except core.PBError as ex:
            return _err(ex)

    return router
