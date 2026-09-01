"""Response-option and submitted-response schemas. See SPEC section 8.2."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VoteOption(BaseModel):
    """Plus/minus vote, optionally with a comment."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["vote"] = "vote"
    # A ballot needs at least two distinct choices to be meaningful: a
    # single-value set (e.g. just "+1") leaves voters no way to abstain or
    # oppose, so reject it at the source (see issue #34). The four-value
    # default stays the sensible common case.
    allowed_values: list[Literal["+1", "+0", "-0", "-1"]] = Field(
        default_factory=lambda: ["+1", "+0", "-0", "-1"],
        min_length=2,
    )
    allow_comment: bool = True

    @field_validator("allowed_values")
    @classmethod
    def _at_least_two_distinct(
        cls, values: list[str]
    ) -> list[str]:
        # min_length=2 alone would accept ["+1", "+1"]; require two
        # *distinct* choices so the ballot is genuinely meaningful.
        if len(set(values)) < 2:
            raise ValueError("allowed_values must contain at least two distinct values")
        return values


class LazyConsensusOption(BaseModel):
    """Silence is assent; the only meaningful response is an objection."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["lazy_consensus"] = "lazy_consensus"
    allow_comment: bool = True


class FreeTextOption(BaseModel):
    """Catch-all for survey-style follow-ups."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["free_text"] = "free_text"
    max_length: int = 4000


ResponseOption = Annotated[
    VoteOption | LazyConsensusOption | FreeTextOption,
    Field(discriminator="kind"),
]


class VoteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["vote"] = "vote"
    value: Literal["+1", "+0", "-0", "-1"]
    comment: str | None = None


class LazyConsensusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["lazy_consensus"] = "lazy_consensus"
    objection: bool
    comment: str | None = None


class FreeTextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["free_text"] = "free_text"
    text: str


SubmittedResponse = Annotated[
    VoteResponse | LazyConsensusResponse | FreeTextResponse,
    Field(discriminator="kind"),
]
