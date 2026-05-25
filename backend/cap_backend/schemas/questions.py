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
    pending: list[Question]


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
    """Body for ``POST /question`` (reserved for a future iteration)."""

    model_config = ConfigDict(extra="forbid")

    request_id: RequestID
    project_id: str
    title: str = Field(..., max_length=200)
    description: str = Field(..., max_length=10_000)
    target_audience: str
    approval_type: Literal[
        "unanimous_approval",
        "majority_approval",
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
