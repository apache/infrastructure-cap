"""Shared schema primitives. See SPEC section 8.1."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

ASFUserID = Annotated[
    str,
    Field(
        min_length=1,
        max_length=32,
        pattern=r"^[a-z][a-z0-9_-]*$",
        description="ASF user id (Unix-name style: lowercase ASCII, starts with a letter).",
    ),
]

RequestID = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        description=(
            "Opaque identifier (ULID/UUID) for a CAP request. Globally unique "
            "across the questions table and server-assigned on INSERT; clients "
            "MUST NOT supply it."
        ),
    ),
]

QuestionID = Annotated[
    int,
    Field(
        ge=1,
        description=(
            "Monotonic numerical id issued by SQLite's AUTOINCREMENT sequence. "
            "Globally unique and server-assigned on INSERT; clients MUST NOT "
            "supply it."
        ),
    ),
]

IsoTimestamp = Annotated[
    datetime,
    Field(
        description="UTC timestamp serialized as ISO 8601.",
    ),
]
