"""Åtkomstskydd för gränssnittet och API:t tills SSO finns (SPEC 10, ÖPPEN FRÅGA 6).

Är `VSK_ACCESS_PASSWORD` satt kräver allt utom /health HTTP Basic-inloggning (valfritt användarnamn,
lösenordet
jämförs i konstant tid). Utan lösenord är uppladdning av underlag avstängd (`uploads_allowed`): kundmaterial
läggs aldrig på en öppen adress.
"""

from __future__ import annotations

import base64
import binascii
import os
import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

OPEN_PATHS = ("/health",)


def access_password() -> str | None:
    return os.environ.get("VSK_ACCESS_PASSWORD") or None


def uploads_allowed() -> bool:
    return access_password() is not None


def user_of(request: Request) -> str | None:
    """Användarnamnet ur Basic-huvudet om lösenordet stämmer, annars None."""
    pw = access_password()
    header = request.headers.get("authorization", "")
    if pw is None or not header.lower().startswith("basic "):
        return None
    try:
        user, _, given = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return None
    return (user or "granskare") if secrets.compare_digest(given.encode(), pw.encode()) else None


class AccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if access_password() is None or request.url.path in OPEN_PATHS:
            return await call_next(request)
        if user_of(request) is None:
            return Response(
                "Inloggning krävs",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="VS-Kalkyl", charset="UTF-8"'},
            )
        return await call_next(request)
