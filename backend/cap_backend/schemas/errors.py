"""Error response schemas. Kept separate so they can be referenced from any
route that needs to document a non-2xx response in the OpenAPI document."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AuthenticationRequired(BaseModel):
    """Body returned by the global ``before_request`` hook on 401."""

    model_config = ConfigDict(extra="forbid")

    error: str = "authentication_required"
    login_url: str


class ErrorMessage(BaseModel):
    """Generic error envelope for 4xx responses outside the auth hook.

    Routes that need to attach additional context (e.g. the question's
    current ``status`` on a 409) include those keys in the body too; this
    schema documents the minimum guaranteed shape.
    """

    model_config = ConfigDict(extra="allow")

    error: str
