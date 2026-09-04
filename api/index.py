"""Vercel serverless entrypoint."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from app.main import app
except Exception:
    _tb = traceback.format_exc()
    _listing = "\n".join(
        sorted(
            str(p.relative_to(ROOT))
            for p in ROOT.rglob("*")
            if "__pycache__" not in str(p)
        )
    )

    async def app(scope, receive, send):  # type: ignore[misc]
        if scope["type"] != "http":
            return
        body = (
            f"IMPORT FAILED\n\n{_tb}\n\n"
            f"sys.path:\n{sys.path}\n\n"
            f"BUNDLE CONTENTS:\n{_listing}"
        ).encode()
        await send({
            "type": "http.response.start",
            "status": 500,
            "headers": [(b"content-type", b"text/plain; charset=utf-8")],
        })
        await send({"type": "http.response.body", "body": body})

__all__ = ["app"]
