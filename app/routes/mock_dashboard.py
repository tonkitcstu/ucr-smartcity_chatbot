"""DEV-ONLY mock dashboard for eyeballing the API during development.

NOT for production — registered in main.py only when ENV != "production",
so neither /mock nor /mock/token exists in a production deploy.

Two endpoints, same origin as the API so there is no CORS to fight:
  GET /mock        -> serves a self-contained HTML page (static/mock_dashboard.html)
  GET /mock/token  -> mints a short-lived admin JWT signed with the app's
                      SECRET_KEY, so the page can call the JWT-protected
                      /api/dashboard/* endpoints. (Dev convenience only.)

The page consumes the REAL dashboard API — it proves the API returns the
captured survey data (payload + location + photo) correctly.
"""
from pathlib import Path
from datetime import datetime, timedelta

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from jose import jwt

from app.utils.auth import SECRET_KEY, ALGORITHM

router = APIRouter(prefix="/mock", tags=["mock-dashboard"])

_HTML_FILE = Path(__file__).resolve().parent.parent / "static" / "mock_dashboard.html"


@router.get("/token")
async def mint_dev_token():
    """Issue an admin JWT for the mock page (dev/demo only)."""
    payload = {
        "sub": "mock-admin",
        "role": "admin",
        "exp": datetime.utcnow() + timedelta(hours=2),
    }
    return JSONResponse({"token": jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)})


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def mock_page():
    return HTMLResponse(_HTML_FILE.read_text(encoding="utf-8"))
