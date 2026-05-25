"""``/api`` endpoint serving the cached OpenAPI document. See SPEC section 9.9."""

from __future__ import annotations

import json
from typing import Any

from quart import Blueprint, Response, current_app

openapi_bp = Blueprint("openapi", __name__)

_CACHE_KEY = "_cap_openapi_cache"


def _build_document(app: Any) -> dict[str, Any]:
    schema_ext = app.extensions.get("QUART_SCHEMA")
    if schema_ext is None:
        # quart-schema wasn't wired up: fall back to a minimal stub so the
        # endpoint stays reachable (tests can exercise it without the full
        # extension installed).
        return {
            "openapi": "3.1.0",
            "info": {"title": app.name, "version": "0.1.0"},
            "paths": {},
        }
    document = schema_ext.openapi_provider.schema()
    if hasattr(document, "model_dump"):
        return document.model_dump(exclude_none=True, by_alias=True)
    return dict(document)


@openapi_bp.get("/api")
async def openapi_document() -> Response:
    """Return the OpenAPI 3.x document for the entire service."""
    cache = current_app.extensions.setdefault(_CACHE_KEY, {})
    body = cache.get("body")
    if body is None:
        document = _build_document(current_app)
        body = json.dumps(document).encode("utf-8")
        cache["body"] = body

    response = Response(body, status=200, content_type="application/json")
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


def invalidate_cache(app: Any) -> None:
    """Drop the cached OpenAPI body so it is regenerated on the next request."""
    app.extensions.pop(_CACHE_KEY, None)
