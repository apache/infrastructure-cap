"""App factory. See SPEC section 5."""

from __future__ import annotations

import logging
import os
from functools import wraps
from typing import Any

from cap_backend.config import Settings, load_settings


def _configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.logging.level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _normalize_response_value(value: Any) -> Any:
    """Convert response payloads that ``quart-schema`` cannot serialize.

    asfquart's built-in ``/auth`` handler returns its ``ClientSession``
    instance directly when the caller is logged in. ``ClientSession``
    subclasses ``dict``, so ``quart-schema``'s response converter dispatches
    to ``TypeAdapter(type(raw)).dump_python(raw)`` and pydantic raises
    ``PydanticSchemaGenerationError`` because ``ClientSession`` isn't a
    pydantic-shaped type. Downgrading it to a plain ``dict`` here sidesteps
    the introspection without changing the wire format.
    """
    try:
        from asfquart.session import ClientSession  # noqa: PLC0415
    except ImportError:  # pragma: no cover - asfquart is declared as a dep
        return value

    if isinstance(value, ClientSession):
        return dict(value)
    return value


def _install_response_normalizer(app: Any) -> None:
    """Wrap ``app.make_response`` to normalize problematic payloads.

    Quart calls our wrapper first, we strip the ``ClientSession`` wrapper
    (and any tuple-shaped variant of it), and only then hand off to the
    quart-schema-wrapped ``make_response``.
    """
    original = app.make_response

    @wraps(original)
    async def make_response(result: Any) -> Any:
        if isinstance(result, tuple):
            head, *rest = result
            result = (_normalize_response_value(head), *rest)
        else:
            result = _normalize_response_value(result)
        return await original(result)

    app.make_response = make_response


def _init_quart_schema(app: Any) -> None:
    """Attach quart-schema to ``app`` if it is installed."""
    try:
        from quart_schema import Info, QuartSchema  # noqa: PLC0415
    except ImportError:  # pragma: no cover - dependency is declared
        return

    QuartSchema(
        app,
        # /api is served by our own blueprint with caching headers, so
        # disable the built-in document path. The UI helpers are not
        # part of the spec; keep them off too.
        openapi_path=None,
        redoc_ui_path=None,
        scalar_ui_path=None,
        swagger_ui_path=None,
        info=Info(title="ASF Infra CAP Backend", version="0.1.1"),
    )
    # Install our normalizer AFTER quart-schema wraps make_response so it
    # runs first and feeds quart-schema's converter a plain dict.
    _install_response_normalizer(app)


def _construct_app(name: str, settings: Settings) -> Any:
    """Build the underlying QuartApp (asfquart) or a plain Quart fallback."""
    try:
        import asfquart  # noqa: PLC0415
        import asfquart.generics

        asfquart.generics.OAUTH_URL_INIT = "https://oauth.apache.org/auth?state=%s&redirect_uri=%s"
        asfquart.generics.OAUTH_URL_CALLBACK = "https://oauth.apache.org/token?code=%s"
        return asfquart.construct(
            name,
            oauth="/api/auth",
        )
    except Exception:  # noqa: BLE001 - any failure in asfquart construction
        # In a constrained environment (e.g. unit tests without an asfquart
        # token file on disk) fall back to a plain Quart app so tests can
        # still exercise the route layer.
        from quart import Quart  # noqa: PLC0415

        return Quart(name)


def build_app(settings: Settings | None = None) -> Any:
    """Construct and return the application, wired with routes and DB.

    The returned object is an ``asfquart.base.QuartApp`` (or a plain
    ``quart.Quart`` if asfquart is not constructable in this environment),
    so callers can use ``.runx(...)`` for production or ``.test_client()``
    for tests.
    """
    if settings is None:
        settings = load_settings()
    _configure_logging(settings)

    app = _construct_app("cap_backend", settings)

    # Make sure the database file's parent directory exists before we open
    # it; this is the most common dev-environment misstep.
    db_path = settings.database.path
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)

    from cap_backend.auth import require_authentication  # noqa: PLC0415
    from cap_backend.db import Database  # noqa: PLC0415
    from cap_backend.openapi import openapi_bp  # noqa: PLC0415
    from cap_backend.pubsub import PubsubPublisher  # noqa: PLC0415
    from cap_backend.routes.questions import questions_bp  # noqa: PLC0415
    from cap_backend.routes.tokens import tokens_bp  # noqa: PLC0415
    from cap_backend.tokens import (  # noqa: PLC0415
        RoleAccountCredential,
        TokenStore,
        build_token_handler,
    )

    database = Database(db_path)
    app.extensions["cap_db"] = database
    app.extensions["cap_settings"] = settings

    # In-memory personal access token store. Tokens do not survive a restart
    # and are not shared between worker processes; see SPEC §6.4.
    token_store = TokenStore()
    app.extensions["cap_tokens"] = token_store
    # Index configured role accounts by the SHA-256 digest of their permanent
    # token so the handler can resolve a presented bearer token in O(1).
    role_accounts = {
        account.hash: RoleAccountCredential(uid=uid, fullname=account.fullname)
        for uid, account in settings.roleaccounts.items()
    }
    # Wire the bearer-token handler into asfquart so that
    # ``Authorization: bearer <token>`` requests resolve to a session
    # whose ``metadata.scope`` carries the issued scope list.
    app.token_handler = build_token_handler(token_store, role_accounts)

    _init_quart_schema(app)

    # Every backend route is namespaced under /api/. The OpenAPI document
    # lives at /api/api and Swagger UI at /api/docs (both served by the
    # openapi blueprint, whose paths already include the prefix); questions
    # and tokens get the prefix injected via url_prefix below.
    app.register_blueprint(openapi_bp)
    app.register_blueprint(questions_bp, url_prefix="/api")
    app.register_blueprint(tokens_bp, url_prefix="/api")

    app.before_request(require_authentication)

    # Lifecycle: register pubsub *after* the db hook so its teardown runs
    # *before* the db is closed (Quart unwinds while_serving generators in
    # LIFO order). The publisher reads from db.conn and writes the cursor,
    # so it must be torn down before we drop the connection.
    @app.while_serving
    async def _close_db():
        try:
            yield
        finally:
            database.close()

    @app.while_serving
    async def _run_pubsub():
        publisher = PubsubPublisher(database, settings)
        app.extensions["cap_pubsub"] = publisher
        await publisher.start()
        try:
            yield
        finally:
            await publisher.stop()

    return app
