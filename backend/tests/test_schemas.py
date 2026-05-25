"""Schema round-trip tests. See SPEC section 12 ('Schema round-tripping')."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from cap_backend.schemas import (
    FreeTextOption,
    FreeTextResponse,
    LazyConsensusOption,
    LazyConsensusResponse,
    ListResponse,
    Question,
    VoteOption,
    VoteResponse,
)


def _question_payload(**overrides):
    base = {
        "question_id": 4217,
        "request_id": "req_01HZ",
        "project_id": "seapony",
        "title": "Apache SeaPony: enable branch protection on main",
        "description": "...",
        "requester": "carol",
        "target_audience": "PMC: Apache SeaPony",
        "created_at": "2026-05-21T09:00:00Z",
        "closes_at": "2026-05-24T09:00:00Z",
        "approval_type": "majority_approval",
        "is_binding": True,
        "is_private": False,
        "response_option": {
            "kind": "vote",
            "allowed_values": ["+1", "+0", "-0", "-1"],
            "allow_comment": True,
        },
        "permalink": None,
        "status": "open",
        "outcome": None,
        "viewer_is_binding": True,
        "time_remaining_seconds": 259200,
    }
    base.update(overrides)
    return base


def test_question_round_trip():
    q = Question.model_validate(_question_payload())
    again = Question.model_validate_json(q.model_dump_json())
    assert again == q


def test_question_extra_field_forbidden():
    with pytest.raises(ValidationError):
        Question.model_validate(_question_payload(unknown_field=1))


def test_list_response_empty_pending():
    body = ListResponse(user="alice", pending=[])
    assert body.model_dump()["pending"] == []


def test_response_option_discriminator_picks_correct_variant():
    q = Question.model_validate(
        _question_payload(
            response_option={"kind": "lazy_consensus", "allow_comment": False},
        )
    )
    assert isinstance(q.response_option, LazyConsensusOption)
    assert q.response_option.allow_comment is False

    q = Question.model_validate(
        _question_payload(response_option={"kind": "free_text", "max_length": 1024})
    )
    assert isinstance(q.response_option, FreeTextOption)
    assert q.response_option.max_length == 1024

    q = Question.model_validate(_question_payload())
    assert isinstance(q.response_option, VoteOption)


def test_submitted_response_discriminator():
    vote = VoteResponse(value="+1", comment="LGTM")
    again = VoteResponse.model_validate_json(vote.model_dump_json())
    assert again == vote

    lazy = LazyConsensusResponse(objection=True, comment="hold on")
    again = LazyConsensusResponse.model_validate_json(lazy.model_dump_json())
    assert again == lazy

    text = FreeTextResponse(text="some notes")
    again = FreeTextResponse.model_validate_json(text.model_dump_json())
    assert again == text


def test_asfuserid_pattern_enforced():
    with pytest.raises(ValidationError):
        # uppercase is not allowed
        ListResponse(user="Alice", pending=[])
    with pytest.raises(ValidationError):
        # leading digit is not allowed
        ListResponse(user="1foo", pending=[])


def test_question_time_remaining_required():
    payload = _question_payload()
    payload.pop("time_remaining_seconds")
    with pytest.raises(ValidationError):
        Question.model_validate(payload)


def test_iso_timestamps_serialize_with_tz():
    payload = _question_payload()
    q = Question.model_validate(payload)
    dumped = q.model_dump(mode="json")
    # ISO 8601 with timezone (Z or +00:00) must be preserved on round-trip.
    parsed = datetime.fromisoformat(dumped["created_at"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.astimezone(UTC) == datetime(2026, 5, 21, 9, 0, tzinfo=UTC)
