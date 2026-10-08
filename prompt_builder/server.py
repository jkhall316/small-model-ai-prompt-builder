"""Standalone server:  prompt-builder  (or: python -m prompt_builder.server)

Serves the page at /  and the API under /api/pb.  Configure with environment variables (see README) or PB_CONFIG=path.json.
"""
from __future__ import annotations

import argparse
import os
import re

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import PAGE, STATIC_DIR, __version__
from .api import create_router
from .settings import Settings


def create_app(settings: Settings | None = None, allowed_hosts: str | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Small Model AI Prompt Builder", version=__version__)

    # Optional host allow-list (regex). Default: only loopback names, because the API proxies to your model.
    host_re = re.compile(allowed_hosts or os.environ.get("PB_ALLOWED_HOSTS") or r"^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", re.I)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not host_re.match(request.headers.get("host", "")):
            return JSONResponse({"error": "host not allowed (set PB_ALLOWED_HOSTS to a regex to open it up)"}, 403)
        return await call_next(request)

    app.include_router(create_router(settings))
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(STATIC_DIR, PAGE))

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "version": __version__}

    return app


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    p = argparse.ArgumentParser(prog="prompt-builder", description="Small Model AI Prompt Builder")
    from .settings import SettingsError

    p.add_argument("--host", default=os.environ.get("PB_HOST") or "127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.environ.get("PB_PORT") or "7810"))
    p.add_argument("--open", action="store_true", help="open the page in a browser")
    a = p.parse_args(argv)
    try:
        app = create_app()
    except SettingsError as ex:
        raise SystemExit(f"prompt-builder: bad configuration — {ex}")
    if a.open:
        import threading, webbrowser
        browse_host = "127.0.0.1" if a.host in ("0.0.0.0", "::", "") else a.host
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{browse_host}:{a.port}")).start()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
