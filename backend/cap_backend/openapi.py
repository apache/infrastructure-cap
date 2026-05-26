"""``/api/api`` endpoint serving the cached OpenAPI document. See SPEC §9.9.

Also hosts ``/api/docs``, a public Swagger UI page that renders the
``/api/api`` document (SPEC §9.10).
"""

from __future__ import annotations

import json
from typing import Any

from quart import Blueprint, Response, current_app

openapi_bp = Blueprint("openapi", __name__)

_CACHE_KEY = "_cap_openapi_cache"

# Pinned major.minor.patch of swagger-ui-dist served from a public CDN.
# Bumping the version is a one-line change here; pinning protects us from a
# CDN-side surprise during a major-version rollover.
_SWAGGER_UI_VERSION = "5.18.2"
_SWAGGER_UI_HTML = f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8">
    <title>CAP Backend API documentation</title>
    <link rel="stylesheet"
          href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@{_SWAGGER_UI_VERSION}/swagger-ui.css">
    <style>body {{ margin: 0; }}</style>
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@{_SWAGGER_UI_VERSION}/swagger-ui-bundle.js"
            crossorigin></script>
    <script>
      window.onload = () => {{
        window.ui = SwaggerUIBundle({{
          url: '/api/api',
          dom_id: '#swagger-ui',
          deepLinking: true,
          presets: [
            SwaggerUIBundle.presets.apis,
            SwaggerUIBundle.SwaggerUIStandalonePreset,
          ],
        }});
      }};
    </script>
  </body>
</html>
"""


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
    document["paths"].pop("/static/{filename}", None)  # pop out the asfquart quirky endpoint
    if hasattr(document, "model_dump"):
        return document.model_dump(exclude_none=True, by_alias=True)
    return dict(document)


@openapi_bp.get("/api/api")
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


@openapi_bp.get("/api/docs")
async def openapi_docs() -> Response:
    """Return a Swagger UI HTML page rendering the ``/api/api`` document."""
    response = Response(_SWAGGER_UI_HTML, status=200, content_type="text/html; charset=utf-8")
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


def invalidate_cache(app: Any) -> None:
    """Drop the cached OpenAPI body so it is regenerated on the next request."""
    app.extensions.pop(_CACHE_KEY, None)
