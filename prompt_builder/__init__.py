"""Small Model AI Prompt Builder.

A single-page prompt builder for AI coding assistants (Claude, Cursor, Antigravity, OpenAI, Gemini, Grok) that a
*small, local* model turns into a conversation: you describe the project, it asks for what is missing, then the
page assembles the prompt deterministically from the filled form.

Plug it into anything:

    from fastapi import FastAPI
    from prompt_builder import Settings, create_router, STATIC_DIR
    app = FastAPI()
    app.include_router(create_router(Settings.from_env()))          # /api/pb/...
    app.mount("/pb", StaticFiles(directory=STATIC_DIR), name="pb")  # /pb/prompt-builder.html

Or run it on its own:  `prompt-builder`  (see README).
"""
from pathlib import Path

from .settings import Settings
from .api import create_router
from .core import PBError, tidy, chat, status

__version__ = "0.1.0"
STATIC_DIR = str(Path(__file__).resolve().parent / "static")
PAGE = "prompt-builder.html"

__all__ = ["Settings", "create_router", "STATIC_DIR", "PAGE", "PBError", "tidy", "chat", "status", "__version__"]
