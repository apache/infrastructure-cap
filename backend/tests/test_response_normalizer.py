"""Regression test for the asfquart ``/auth`` ClientSession serialization bug.

asfquart's ``/auth`` handler returns its ``ClientSession`` (a ``dict``
subclass) directly when the caller is logged in. ``quart-schema``'s response
wrapper then asks pydantic to introspect ``type(value)`` and raises
``PydanticSchemaGenerationError`` because ``ClientSession`` isn't a
pydantic-shaped type. ``app.py`` installs a normalizer that downgrades the
``ClientSession`` to a plain ``dict`` before quart-schema sees it.
"""

from __future__ import annotations

import json

import pytest
from asfquart.session import ClientSession


async def test_make_response_handles_client_session(app, stub_session):
    """A handler returning a ClientSession must serialize without error."""

    @app.route("/__test_client_session__")
    async def _emit():
        return ClientSession({"uid": "alice", "pmcs": ["seapony"]})

    client = app.test_client()
    response = await client.get(
        "/__test_client_session__",
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    body = json.loads(await response.get_data())
    assert body["uid"] == "alice"
    assert body["committees"] == ["seapony"]


async def test_make_response_handles_client_session_tuple(app, stub_session):
    """The tuple form ``(value, status)`` must also be normalized."""

    @app.route("/__test_client_session_tuple__")
    async def _emit():
        return ClientSession({"uid": "bob", "pmcs": []}), 201

    client = app.test_client()
    response = await client.get(
        "/__test_client_session_tuple__",
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 201
    body = json.loads(await response.get_data())
    assert body["uid"] == "bob"


def test_model_dump_rejects_raw_client_session_without_fix():
    """Document the underlying quart-schema bug: model_dump on a
    ClientSession raises PydanticSchemaGenerationError. The application's
    normalizer is what makes the request path safe."""

    from pydantic.errors import PydanticSchemaGenerationError
    from quart_schema.conversion import model_dump

    session = ClientSession({"uid": "alice", "pmcs": []})
    # Plain dict works:
    model_dump(dict(session))
    # ClientSession does not:
    with pytest.raises(PydanticSchemaGenerationError):
        model_dump(session)
