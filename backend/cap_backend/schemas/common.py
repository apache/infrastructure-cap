"""Shared schema primitives. See SPEC section 8.1."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

# Length limits shared by the request/response models and re-checked in the
# route handlers. The frontend mirrors these in ``frontend/src/lib/limits.ts``;
# keep the two in sync.
TITLE_MAX_LENGTH = 200
TARGET_AUDIENCE_MAX_LENGTH = 200
DESCRIPTION_MAX_LENGTH = 2500
COMMENT_MAX_LENGTH = 2500

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
