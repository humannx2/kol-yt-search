"""Vercel serverless entrypoint — re-exports the FastAPI app."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Ensure project root (backend/) is on sys.path for `import app`.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# #region agent log
def _debug_log(message: str, data: dict) -> None:
    try:
        import json
        import time
        import urllib.request

        payload = {
            "sessionId": "6b9c45",
            "hypothesisId": "E",
            "location": "api/index.py",
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
            "runId": "vercel-500",
        }
        req = urllib.request.Request(
            "http://127.0.0.1:7909/ingest/64ba1ad6-78b7-4e0c-89f8-7fe1a6d84a5a",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Debug-Session-Id": "6b9c45",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass


# #endregion

try:
    from app.main import app as app

    # #region agent log
    _debug_log("import_ok", {"root": str(_ROOT), "routes": len(app.routes)})
    # #endregion
except Exception as exc:  # pragma: no cover - deploy diagnostics
    # #region agent log
    _debug_log(
        "import_failed",
        {
            "error": type(exc).__name__,
            "detail": str(exc)[:300],
            "traceback": traceback.format_exc()[-800:],
            "root": str(_ROOT),
            "sys_path0": sys.path[:3],
        },
    )
    # #endregion
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI(title="boot-error")

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
    async def boot_error(full_path: str = "") -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": type(exc).__name__,
                "detail": str(exc),
                "traceback": traceback.format_exc().splitlines()[-20:],
            },
        )
