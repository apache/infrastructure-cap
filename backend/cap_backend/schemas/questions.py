"""Question and list-response schemas. See SPEC section 8.3."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from cap_backend.schemas.common import ASFUserID, IsoTimestamp, QuestionID, RequestID
from cap_backend.schemas.responses import ResponseOption, SubmittedResponse


class Question(BaseModel):
    """A single pending CAP item shown to one voter for one CAP request."""

    model_config = ConfigDict(extra="forbid")

    question_id: QuestionID
    request_id: RequestID
    project_id: str

    title: str = Field(..., max_length=200)
    description: str = Field(..., max_length=10_000)

    requester: ASFUserID
    target_audience: str
    created_at: IsoTimestamp
    closes_at: IsoTimestamp

    approval_type: Literal[
        "unanimous_approval",
        "majority_approval",
        "simple_majority",
        "lazy_consensus",
    ]

    is_binding: bool
    is_private: bool = False

    response_option: ResponseOption

    permalink: str | None = None

    status: Literal["open", "resolved", "removed"] = "open"
    outcome: (
        Literal[
            "approved",
            "vetoed",
            "insufficient_votes",
            "withdrawn",
        ]
        | None
    ) = None

    viewer_is_binding: bool
    time_remaining_seconds: int


class ListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: ASFUserID
    # ``pending``: currently-open questions visible to the caller. Sorted
    # by ``closes_at ASC, question_id ASC`` so the soonest-to-close items
    # come first. See SPEC §9.1.
    pending: list[Question]
    # ``recent``: every question (open, resolved, or removed) whose
    # ``updated_at`` falls within the last 14 days and which the caller
    # is permitted to view. Sorted by ``updated_at DESC, question_id DESC``
    # so the most-recently-touched items come first. See SPEC §9.1.
    recent: list[Question] = Field(default_factory=list)


class PublicListResponse(BaseModel):
    """Body returned by ``GET /api/publist`` (SPEC §9.13).

    Holds every non-private question that is either still open or was
    last touched within the past 14 days. The endpoint is unauthenticated,
    so there is no ``user`` field and ``viewer_is_binding`` on every row
    is always ``False`` (no session implies no committee membership).
    """

    model_config = ConfigDict(extra="forbid")

    questions: list[Question]


class StoredResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_id: str
    question_id: QuestionID
    voter: ASFUserID
    response_kind: Literal["vote", "lazy_consensus", "free_text"]
    response: SubmittedResponse
    comment: str | None
    is_binding: bool
    is_veto: bool
    created_at: IsoTimestamp


class QuestionDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Question
    responses: list[StoredResponse]


class CreateQuestionRequest(BaseModel):
    """Body for ``POST /question``.

    ``request_id`` and ``question_id`` are server-assigned (SPEC §9.2) and
    must not appear in the request body; the model rejects them via
    ``extra="forbid"``.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str
    title: str = Field(..., max_length=200)
    description: str = Field(..., max_length=10_000)
    target_audience: str
    approval_type: Literal[
        "unanimous_approval",
        "majority_approval",
        "simple_majority",
        "lazy_consensus",
    ]
    is_binding: bool
    is_private: bool = False
    response_option: ResponseOption
    closes_at: IsoTimestamp


class EditQuestionRequest(BaseModel):
    """Body for ``PATCH /question/{id}`` (reserved for a future iteration)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    target_audience: str | None = None
    closes_at: IsoTimestamp | None = None
    is_private: bool | None = None
    response_option: ResponseOption | None = None


class ResolutionRecord(BaseModel):
    """Body returned by ``GET /resolution/{id}``."""

    model_config = ConfigDict(extra="forbid")

    question_id: QuestionID
    outcome: Literal["approved", "vetoed", "insufficient_votes", "withdrawn"]
    resolved_at: IsoTimestamp | None = None
    permalink: str
    question: Question
    tally: dict[str, Any] | None = None
    voters: list[StoredResponse] = Field(default_factory=list)
